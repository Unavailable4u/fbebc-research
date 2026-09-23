#!/usr/bin/env python3
"""scripts/usage_report.py -- measure real Sigma token usage and project what
experiment size the free-tier daily caps actually allow.

    python scripts/usage_report.py                      # all logged calls
    python scripts/usage_report.py --days 8 --arms 6    # + projection

Why this exists: sigma/budget.py used to assume the requests/day cap was the
binding constraint. The provider ALSO caps tokens/day, and circle_packing's
prompt is ~870 input tokens before any reasoning/output, so the token cap
very likely binds first. This turns that guess into a measured number using
the `usage` block logged by sigma/client.py on every call.

Limits are arguments, not constants, because free-tier limits move: read them
off your own account's limits page and pass them in.
"""

import argparse
import json
import statistics
import sys
from pathlib import Path

DEFAULT_LOG = Path.home() / ".fbebc_sigma_budget.usage.jsonl"


def load_rows(path: Path, since_date: str | None = None) -> list[dict]:
    rows = []
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return rows
    for line in lines:
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if since_date and r.get("ts_utc", "")[:10] < since_date:
            continue
        rows.append(r)
    return rows


def _pctl(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    i = min(len(sorted_vals) - 1, max(0, int(round(q * (len(sorted_vals) - 1)))))
    return sorted_vals[i]


def summarize(rows: list[dict]) -> dict:
    totals = sorted(r["total_tokens"] for r in rows)
    prompts = [r["prompt_tokens"] for r in rows]
    comps = [r["completion_tokens"] for r in rows]
    reasoning = [r["reasoning_tokens"] for r in rows if r.get("reasoning_tokens") is not None]
    return {
        "n_calls": len(rows),
        "mean_total": statistics.fmean(totals) if totals else 0.0,
        "median_total": statistics.median(totals) if totals else 0.0,
        "p95_total": _pctl(totals, 0.95),
        "max_total": totals[-1] if totals else 0,
        "mean_prompt": statistics.fmean(prompts) if prompts else 0.0,
        "mean_completion": statistics.fmean(comps) if comps else 0.0,
        "mean_reasoning": statistics.fmean(reasoning) if reasoning else None,
        "finish_length": sum(1 for r in rows if r.get("finish_reason") == "length"),
    }


def project(*, tokens_per_call: float, tpd: int, rpd: int, calls_per_gen: float, days: float, arms: int) -> dict:
    """What the daily caps allow. Pure arithmetic, no I/O."""
    token_limited = tpd / tokens_per_call if tokens_per_call > 0 else float("inf")
    calls_per_day = min(float(rpd), token_limited)
    gens_per_day = calls_per_day / calls_per_gen
    total_gens = gens_per_day * days
    return {
        "calls_per_day": calls_per_day,
        "binding_limit": "tokens/day" if token_limited < rpd else "requests/day",
        "gens_per_day": gens_per_day,
        "total_gens": total_gens,
        "gens_per_arm": total_gens / arms if arms else total_gens,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--log", default=str(DEFAULT_LOG))
    ap.add_argument("--since", default=None, help="only calls on/after this UTC date, YYYY-MM-DD")
    ap.add_argument("--tpd", type=int, default=200_000, help="provider tokens/day limit (verify on your account)")
    ap.add_argument("--rpd", type=int, default=1_000, help="provider requests/day limit (verify on your account)")
    ap.add_argument("--calls-per-gen", type=float, default=1.6,
                    help="Sigma calls per generation (summarize_ledgers.py prints the measured value)")
    ap.add_argument("--days", type=float, default=None, help="days of quota you can spend (enables projection)")
    ap.add_argument("--arms", type=int, default=6, help="number of arms sharing that quota")
    args = ap.parse_args()

    rows = load_rows(Path(args.log), args.since)
    if not rows:
        print(f"no usage rows in {args.log}. Make some real calls first (python -m sigma.client, or a run).")
        return 1
    s = summarize(rows)
    print(f"calls logged: {s['n_calls']}   (log: {args.log})")
    print(f"tokens/call   mean {s['mean_total']:.0f} | median {s['median_total']:.0f} | p95 {s['p95_total']:.0f} | max {s['max_total']}")
    print(f"  of which    prompt {s['mean_prompt']:.0f} | completion {s['mean_completion']:.0f}"
          + (f" (reasoning {s['mean_reasoning']:.0f})" if s["mean_reasoning"] is not None else ""))
    if s["finish_length"]:
        print(f"  !! {s['finish_length']} call(s) hit finish_reason=length (output truncated / reasoning ate the budget)")

    for label, tok in (("mean", s["mean_total"]), ("p95 (conservative)", s["p95_total"])):
        p = project(tokens_per_call=tok, tpd=args.tpd, rpd=args.rpd, calls_per_gen=args.calls_per_gen,
                    days=args.days or 1, arms=args.arms)
        print(f"\nat {label} tokens/call, limits tpd={args.tpd} rpd={args.rpd}:")
        print(f"  ~{p['calls_per_day']:.0f} calls/day ({p['binding_limit']} binds) "
              f"= ~{p['gens_per_day']:.0f} generations/day at {args.calls_per_gen} calls/gen")
        if args.days:
            print(f"  over {args.days:g} day(s): ~{p['total_gens']:.0f} generations total "
                  f"= ~{p['gens_per_arm']:.0f} per arm across {args.arms} arm(s)")
    cap = int((args.tpd - 3 * s["p95_total"]) // 1000 * 1000)
    print(f"\nsuggested --daily-token-cap: {cap}  (tpd minus ~3 worst-case calls of overshoot margin;"
          f" the provider's window may be rolling rather than UTC-midnight, so treat as a floor)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
