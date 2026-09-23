# sigma/budget.py
#
# Groq's free tier does not queue or soft-fail a request that would exceed
# the daily cap -- per Groq's own docs, exceeding any limit (RPM/TPM/RPD/TPD)
# returns an immediate 429. Refusing client-side, before spending a network
# round trip, gets you the same outcome with a clearer local error and one
# fewer wasted request against an already-scarce daily allowance.
#
# Week 3 Day 15 correction: this originally tracked REQUEST count only, on
# the assumption that the ~1,000 requests/day cap was "comfortably the
# binding constraint for this pipeline's small per-request token counts."
# That assumption was never measured. The same free tier also carries a
# tokens-per-day (TPD) cap (STATUS.md records 200K/day for gpt-oss-120b as of
# 2026-09-17), and circle_packing's prompt alone is ~870 input tokens before
# any reasoning/output -- at ~1,200-2,500 total tokens per call, TPD allows
# roughly 80-160 calls/day, far below 900. So this now ALSO tracks tokens
# (recorded by sigma/client.py from each response's `usage` block) and can
# enforce an optional local token cap, set a margin below the real TPD.
# The cap is None by default because the right value is an empirical,
# per-account number -- measure it first with scripts/usage_report.py.

import json
import time
from pathlib import Path


class BudgetExceeded(RuntimeError):
    pass


def _today_utc() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


class DailyBudget:
    def __init__(self, path: Path, daily_cap: int, daily_token_cap: int | None = None):
        self.path = Path(path)
        self.daily_cap = daily_cap
        self.daily_token_cap = daily_token_cap

    def _load(self) -> dict:
        try:
            state = json.loads(self.path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return {"date": _today_utc(), "count": 0, "tokens": 0}
        if state.get("date") != _today_utc():
            return {"date": _today_utc(), "count": 0, "tokens": 0}
        state.setdefault("tokens", 0)  # state files written before token tracking existed
        return state

    def _save(self, state: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(state))

    def check_and_reserve(self) -> None:
        """Call once immediately before firing a request. Raises
        BudgetExceeded instead of letting the request go out and 429."""
        state = self._load()
        if state["count"] >= self.daily_cap:
            raise BudgetExceeded(
                f"local daily request budget ({self.daily_cap}) reached for "
                f"{state['date']} UTC. Wait for UTC midnight reset, or pass "
                f"a higher daily_request_cap if your account's real limit "
                f"is higher than this conservative default."
            )
        if self.daily_token_cap is not None and state["tokens"] >= self.daily_token_cap:
            raise BudgetExceeded(
                f"local daily token budget ({self.daily_token_cap}) reached for "
                f"{state['date']} UTC ({state['tokens']} tokens used). Wait for the "
                f"provider's reset, or pass a higher daily_token_cap if your "
                f"account's real limit is higher than this local cap."
            )
        state["count"] += 1
        self._save(state)

    def record_tokens(self, n: int) -> None:
        """Add n tokens (from a response's `usage` block) to today's tally.
        Called AFTER a response arrives, so the cap check in
        check_and_reserve() can overshoot by at most one call's worth --
        set daily_token_cap a margin below the provider's real limit."""
        if not n or n < 0:
            return
        state = self._load()
        state["tokens"] += int(n)
        self._save(state)

    def tokens_used(self) -> int:
        return self._load()["tokens"]

    def remaining(self) -> int:
        state = self._load()
        return max(0, self.daily_cap - state["count"])
