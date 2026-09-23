# sigma/client.py
#
# Sigma's LLM backend. Switched from the research-program-guide's Gemini
# pin to Groq (openai/gpt-oss-120b, free tier) -- a disclosed
# substitution, same as the Levenshtein-for-Zhang-Shasha one: the guide's
# own resource table flags these free-tier numbers as something to "verify
# ... before you start -- these move," so treat this as a swap within the
# spirit of that pin, not a deviation from it. Record which provider/model
# you actually used in the paper's Methods section either way.
#
# Plain REST via urllib, deliberately no groq/openai SDK dependency --
# consistent with the rest of this repo (no numpy either; see
# harness/child.py's docstring). Groq's API is OpenAI-compatible, so this
# is a completely standard POST to /chat/completions.
#
# NOTE: this file was written and code-reviewed in an environment with no
# network egress to api.groq.com, so it could not be exercised against the
# real API before you got it. Run `python -m sigma.client` first thing,
# before wiring it into a real generation loop, to catch anything that
# only shows up against the live API.

import argparse
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

from delta.admission.applicator import DIFF as DIFF_HUNK_RE
from delta.admission.tasks import TaskSpec, get_task

from .budget import BudgetExceeded, DailyBudget
from .prompts import build_messages

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
# llama-3.3-70b-versatile was retired from Groq's free-tier catalog
# (confirmed via a live 404 model_not_found on 2026-09-17) -- gpt-oss-120b
# was the fallback recommendation from the start for exactly this reason:
# Groq's model lineup moves. Check console.groq.com/docs/rate-limits (or
# your account's own limits page) before assuming this is still current.
MODEL = "openai/gpt-oss-120b"

# Conservative default: real free-tier cap on this model is reported around
# 1,000 requests/day (see budget.py's docstring) -- verify on your own
# account and raise this if it's actually higher.
DEFAULT_DAILY_REQUEST_CAP = 900
DEFAULT_BUDGET_PATH = Path.home() / ".fbebc_sigma_budget.json"


# A 429 whose Retry-After exceeds this is a long-window limit (daily
# tokens/requests), not a per-minute one -- sleeping through it inside a
# single propose_diff() call would just hang the run. Surface it as a clean
# BudgetExceeded stop instead (the loop checkpoints and the CLI exits 3).
MAX_429_SLEEP_S = 120.0


class SigmaError(RuntimeError):
    pass


class SigmaProposalError(SigmaError):
    """The API call itself succeeded but the reply was unusable (empty
    content from reasoning exhaustion, or no SEARCH/REPLACE hunk). Distinct
    from a plain SigmaError (network / 4xx / bad key), which must still
    crash the run loudly: delta/loop.py treats THIS type as one wasted
    attempt (logged as E_NO_PROPOSAL, retried) and everything else as fatal.
    """


class SigmaClient:
    def __init__(
        self,
        api_key: str | None = None,
        model: str = MODEL,
        daily_request_cap: int = DEFAULT_DAILY_REQUEST_CAP,
        budget_path: Path = DEFAULT_BUDGET_PATH,
        daily_token_cap: int | None = None,
        usage_log_path: Path | None = None,
    ):
        self.api_key = api_key or os.environ.get("GROQ_API_KEY")
        if not self.api_key:
            raise SigmaError(
                "no Groq API key: pass api_key= or set the GROQ_API_KEY "
                "environment variable. Never hardcode it in source."
            )
        self.model = model
        self.budget = DailyBudget(budget_path, daily_request_cap, daily_token_cap)
        # One JSON line per API response that carried a `usage` block, so
        # scripts/usage_report.py can measure real tokens/call instead of
        # guessing. Defaults to a sibling of the budget file (so tests that
        # point budget_path at tmp_path never touch the real home directory).
        bp = Path(budget_path)
        self.usage_log_path = Path(usage_log_path) if usage_log_path else bp.with_name(bp.stem + ".usage.jsonl")

    def _record_usage(self, payload: dict, finish_reason) -> None:
        usage = payload.get("usage")
        if not isinstance(usage, dict):
            return
        prompt = usage.get("prompt_tokens") or 0
        completion = usage.get("completion_tokens") or 0
        total = usage.get("total_tokens") or (prompt + completion)
        reasoning = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")
        self.budget.record_tokens(total)
        row = {
            "ts_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "model": self.model, "prompt_tokens": prompt, "completion_tokens": completion,
            "reasoning_tokens": reasoning, "total_tokens": total, "finish_reason": finish_reason,
        }
        try:
            self.usage_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.usage_log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
        except OSError:
            pass  # usage logging is diagnostic; never let it break a run

    def propose_diff(
        self,
        *,
        task: TaskSpec,
        parent_src: str,
        prior_rejection: dict | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        reasoning_effort: str = "low",
        timeout_s: int = 30,
        max_retries: int = 3,
    ) -> str:
        """Returns a raw diff string suitable for
        delta.orchestrator.admit_candidate()'s diff_text argument directly
        -- apply_bounded_diff() finds the SEARCH/REPLACE hunk wherever it
        sits in the text via DIFF.finditer(), so no extraction/cleanup of
        surrounding prose or an accidental markdown fence is needed before
        handing it off. This function's own pre-check below exists purely
        so a garbled model response fails with a clear SigmaError instead
        of a more generic E_MALFORMED_DIFF two layers away.

        reasoning_effort matters specifically for gpt-oss models: they are
        reasoning models that can spend the ENTIRE max_tokens budget on an
        internal chain-of-thought before writing anything into `content`,
        leaving it empty with finish_reason="length" (confirmed live against
        this exact model -- see the chat transcript). "low" is deliberately
        the default here: proposing one small, targeted code edit doesn't
        need heavy reasoning, and low effort leaves more of the budget free
        for the actual diff.
        """
        self.budget.check_and_reserve()
        messages = build_messages(task=task, parent_src=parent_src, prior_rejection=prior_rejection)
        body_dict = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if "gpt-oss" in self.model:
            # Only the gpt-oss family supports this param on Groq; sending
            # it to a non-reasoning model risks an unrelated 400.
            body_dict["reasoning_effort"] = reasoning_effort
        body = json.dumps(body_dict).encode("utf-8")
        req = urllib.request.Request(
            GROQ_URL,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                # Cloudflare fronts api.groq.com and blocks the default
                # "Python-urllib/3.x" User-Agent as a bot signature at the
                # edge -- a 403 "error code: 1010" -- before the request
                # ever reaches Groq's own auth/API layer. This is a known,
                # widely-reported issue (see Groq's own community forum)
                # affecting any bare-urllib client, nothing account- or
                # key-specific. Any real identifying string avoids it.
                "User-Agent": "fbebc-sigma-client/1.0",
            },
        )

        last_err: Exception | None = None
        for attempt in range(max_retries):
            try:
                with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                    payload = json.loads(resp.read())
                choice = payload["choices"][0]
                # Record usage BEFORE validating content: an empty-content
                # (reasoning-exhausted) reply still burned tokens against TPD.
                self._record_usage(payload, choice.get("finish_reason"))
                content = choice.get("message", {}).get("content") or ""
                if not content:
                    finish_reason = choice.get("finish_reason")
                    reasoning_tokens = (
                        payload.get("usage", {})
                        .get("completion_tokens_details", {})
                        .get("reasoning_tokens")
                    )
                    raise SigmaProposalError(
                        f"empty content from {self.model} "
                        f"(finish_reason={finish_reason!r}, reasoning_tokens={reasoning_tokens!r}, "
                        f"max_tokens={max_tokens}, reasoning_effort={reasoning_effort!r}). "
                        f"This is the model's reasoning trace consuming the whole token "
                        f"budget before writing an answer -- raise max_tokens and/or lower "
                        f"reasoning_effort further."
                    )
                if not DIFF_HUNK_RE.search(content):
                    raise SigmaProposalError(
                        f"model response contained no SEARCH/REPLACE hunk "
                        f"(got {len(content)} chars): {content[:300]!r}"
                    )
                return content
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")[:500]
                if e.code == 429:
                    wait = _retry_after_seconds(e, default=10.0)
                    if _is_long_window_limit(detail) or wait > MAX_429_SLEEP_S:
                        raise BudgetExceeded(
                            f"Groq 429 on a daily/long-window limit "
                            f"(Retry-After={wait:.0f}s): {detail}"
                        ) from e
                    time.sleep(wait)
                    last_err = SigmaError(f"Groq 429 rate limited: {detail}")
                    continue
                raise SigmaError(f"Groq API error {e.code}: {detail}") from e
            except urllib.error.URLError as e:
                last_err = SigmaError(f"network error calling Groq: {e}")
                time.sleep(2**attempt)
        raise last_err or SigmaError("exhausted retries calling Groq")


def _is_long_window_limit(detail: str) -> bool:
    """Groq's 429 bodies name the exhausted limit, e.g. '... on tokens per
    day (TPD): Limit 200000, Used ...' -- as opposed to '(TPM)'/'(RPM)'
    per-minute limits, which are worth a short sleep-and-retry."""
    d = detail.lower()
    return "per day" in d or "(tpd)" in d or "(rpd)" in d


def _retry_after_seconds(http_error: urllib.error.HTTPError, default: float) -> float:
    try:
        return float(http_error.headers.get("Retry-After"))
    except (TypeError, ValueError, AttributeError):
        return default


def _selftest() -> None:
    """python -m sigma.client [--task circle_packing]
    One real call against the live API, printing the prompt and the raw
    response so you can eyeball whether the model is actually following
    the SEARCH/REPLACE format before spending budget on a real loop."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default="circle_packing", choices=["binpacking", "circle_packing"])
    args = ap.parse_args()

    task = get_task(args.task)
    parent_src = task.seed_path.read_text(encoding="utf-8")
    client = SigmaClient()

    print(f"--- calling Groq ({client.model}) for task={task.name} ---")
    print(f"(local daily budget remaining before this call: {client.budget.remaining()})\n")
    diff = client.propose_diff(task=task, parent_src=parent_src)
    print("--- raw model response ---")
    print(diff)
    print("\n--- does it match the applicator's hunk regex? ---")
    print(bool(DIFF_HUNK_RE.search(diff)))


if __name__ == "__main__":
    _selftest()
