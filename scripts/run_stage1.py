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

Week 3 Day 16-20: a full circle_packing run's call budget (~1,000 Sigma
calls, research-program-guide §1.5) does not fit inside one day's
free-tier request cap. Re-running this exact command tomorrow resumes
automatically from a checkpoint next to the ledger file -- see
WEEK3_SETUP.md for the full multi-day workflow and --seeds for running
several seed-arms in one sitting. Pass --restart to ignore an existing
checkpoint and start over from the task's own P_0 seed.
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from delta import checkpoint as checkpoint_mod  # noqa: E402
from delta.admission.tasks import get_task  # noqa: E402
from delta.control.channel import ControlChannel  # noqa: E402
from delta.integrity import manifest as manifest_mod  # noqa: E402
from delta.ledger.chain import Ledger  # noqa: E402
from delta.loop import run_generations  # noqa: E402
from sigma.budget import BudgetExceeded  # noqa: E402
from sigma.client import SigmaClient  # noqa: E402


def run_one_seed(*, task_name: str, generations: int, seed_base: int, ledger_path: str, restart: bool) -> int:
    task = get_task(task_name)
    ledger = Ledger(ledger_path)
    control = ControlChannel()
    sigma = SigmaClient()  # reads GROQ_API_KEY from the environment
    manifest_roots = [REPO_ROOT / "delta", REPO_ROOT / "harness"]
    work_root = REPO_ROOT / "work"
    work_root.mkdir(exist_ok=True)

    ckpt_path = checkpoint_mod.default_path_for_ledger(Path(ledger_path))
    ckpt = None if restart else checkpoint_mod.load(ckpt_path)
    if ckpt is not None and ckpt.task_name != task_name:
        print(
            f"!!! checkpoint at {ckpt_path} is for task={ckpt.task_name!r}, not "
            f"{task_name!r} -- pass a different --ledger or --restart.", file=sys.stderr,
        )
        return 2
    resume_kwargs = {}
    if ckpt is not None:
        print(
            f"resuming seed-base={seed_base}: generation {ckpt.next_generation_index}, "
            f"best fitness so far {ckpt.best_fitness}"
        )
        resume_kwargs = dict(
            start_generation_index=ckpt.next_generation_index, initial_parent_src=ckpt.parent_src,
            initial_parent_id=ckpt.parent_id, initial_best_fitness=ckpt.best_fitness,
        )

    print(f"task={task.name}  generations={generations}  ledger={ledger_path}")
    print(f"Sigma model={sigma.model}  daily budget remaining={sigma.budget.remaining()}\n")

    exit_code = 0
    summary = None
    try:
        summary = run_generations(
            task=task, n_generations=generations, ledger=ledger,
            work_root=work_root, manifest_roots=manifest_roots, sigma=sigma,
            control=control, seed_base=seed_base, checkpoint_path=ckpt_path,
            stop_exceptions=(BudgetExceeded,), **resume_kwargs,
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
        if summary.stopped_reason == "BudgetExceeded":
            print(
                f"\nStopped early: today's Sigma request budget is used up. Checkpoint saved "
                f"at {ckpt_path} -- re-run this exact command (same --ledger) after the daily "
                f"reset to continue from generation {len(summary.generations) + resume_kwargs.get('start_generation_index', 0)}.",
            )
            return 3

    return exit_code


def _ledger_path_for_seed(base_path: str, seed_base: int, multi: bool) -> str:
    if not multi:
        return base_path
    p = Path(base_path)
    return str(p.with_name(f"{p.stem}.seed{seed_base}{p.suffix}"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--task", default="binpacking", choices=["binpacking", "circle_packing"])
    ap.add_argument(
        "--generations", type=int, default=5,
        help="generations to attempt THIS invocation (per seed-arm) -- not the run's total target. "
             "Re-running the same command continues automatically from a checkpoint; see WEEK3_SETUP.md.",
    )
    ap.add_argument("--seed-base", type=int, default=0, help="ignored if --seeds is given")
    ap.add_argument(
        "--seeds", default=None,
        help="comma-separated seed-base values for running several independent seed-arms in one "
             "sitting, e.g. --seeds 0,1000,2000 (research-program-guide §1.4/§1.5: 3 seeds for the "
             "reported circle_packing result). Stops the whole batch -- without trying later seeds -- "
             "the moment one arm hits today's Sigma budget cap, since the cap is process-wide, not "
             "per-seed; each arm's own checkpoint means re-running tomorrow picks up exactly there.",
    )
    ap.add_argument(
        "--ledger", default=str(REPO_ROOT / "run_ledger.db"),
        help="with --seeds, this is a base path -- each seed-arm gets its own "
             "<stem>.seed<N><suffix> ledger (and matching checkpoint) derived from it automatically.",
    )
    ap.add_argument(
        "--restart", action="store_true",
        help="ignore any existing checkpoint for this task+ledger and start over from the task's P_0 seed.",
    )
    args = ap.parse_args()

    seed_bases = [int(s) for s in args.seeds.split(",")] if args.seeds else [args.seed_base]
    multi = len(seed_bases) > 1

    for i, seed_base in enumerate(seed_bases):
        ledger_path = _ledger_path_for_seed(args.ledger, seed_base, multi)
        if multi:
            print(f"\n=== seed-arm {i + 1}/{len(seed_bases)}: seed-base={seed_base} ===")
        code = run_one_seed(
            task_name=args.task, generations=args.generations, seed_base=seed_base,
            ledger_path=ledger_path, restart=args.restart,
        )
        if code == 3:
            print(
                f"\nStopping the whole batch here (seed-base={seed_base} hit today's budget cap). "
                f"Re-run this exact command tomorrow -- each arm resumes from its own checkpoint.",
                file=sys.stderr,
            )
            return code
        if code != 0:
            return code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
