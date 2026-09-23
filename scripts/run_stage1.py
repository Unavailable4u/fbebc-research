#!/usr/bin/env python3
"""scripts/run_stage1.py — Week 2 Day 12-14: run a real generation loop.

Usage (from repo root):
    python scripts/run_stage1.py --task binpacking --generations 5

Start with --task binpacking (the warm-up task) and a small --generations
count. Per research-program-guide §1.2/§1.4: binpacking is pipeline-
debugging only and is NOT reported in the paper -- circle_packing (week 3)
is the task whose results matter. Don't spend real Sigma budget on
circle_packing runs until a binpacking run has gone cleanly end to end at
least once.

Needs:
  - GROQ_API_KEY set in the environment (never pass it on the command line
    where it'd land in shell history).
  - A real Docker daemon (see WEEK2_SETUP.md) -- evaluate() launches a
    container per candidate.
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from delta.admission.tasks import get_task  # noqa: E402
from delta.control.channel import ControlChannel  # noqa: E402
from delta.integrity import manifest as manifest_mod  # noqa: E402
from delta.ledger.chain import Ledger  # noqa: E402
from delta.loop import run_generations  # noqa: E402
from sigma.client import SigmaClient  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--task", default="binpacking", choices=["binpacking", "circle_packing"])
    ap.add_argument("--generations", type=int, default=5)
    ap.add_argument("--seed-base", type=int, default=0)
    ap.add_argument("--ledger", default=str(REPO_ROOT / "run_ledger.db"))
    args = ap.parse_args()

    task = get_task(args.task)
    ledger = Ledger(args.ledger)
    control = ControlChannel()
    sigma = SigmaClient()  # reads GROQ_API_KEY from the environment
    manifest_roots = [REPO_ROOT / "delta", REPO_ROOT / "harness"]
    work_root = REPO_ROOT / "work"
    work_root.mkdir(exist_ok=True)

    print(f"task={task.name}  generations={args.generations}  ledger={args.ledger}")
    print(f"Sigma model={sigma.model}  daily budget remaining={sigma.budget.remaining()}\n")

    exit_code = 0
    summary = None
    try:
        summary = run_generations(
            task=task, n_generations=args.generations, ledger=ledger,
            work_root=work_root, manifest_roots=manifest_roots, sigma=sigma,
            control=control, seed_base=args.seed_base,
        )
    except manifest_mod.IntegrityViolation as e:
        print(f"\n!!! INTEGRITY VIOLATION -- HALTING: {e}", file=sys.stderr)
        print(
            "Delta itself changed during this run. Do not trust anything after "
            "the last known-good ledger record. Investigate before resuming "
            "(Phase1 guide §5: this is not a recoverable error).",
            file=sys.stderr,
        )
        exit_code = 1
    except SystemExit as e:
        print(f"\nHalted via control channel: {e}", file=sys.stderr)
        exit_code = 1
    finally:
        chain_ok = ledger.verify_chain()
        ledger.close()

    if not chain_ok:
        print("\n!!! LEDGER CHAIN VERIFICATION FAILED -- something is very wrong.", file=sys.stderr)
        return 2

    if summary is not None:
        print(f"\n{len(summary.generations)} generation(s) attempted:")
        for g in summary.generations:
            print(f"  gen {g.generation_index}: {g.outcome:8s} clone={g.clone_id} fitness={g.fitness}")
        print(f"\nBest fitness: {summary.best_fitness}")
        print(f"Sigma daily budget remaining: {sigma.budget.remaining()}")

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
