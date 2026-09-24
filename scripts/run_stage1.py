#!/usr/bin/env python3
"""scripts/run_stage1.py -- run the Stage 1 generation loop.

Smoke test (Week 2 style; --generations = "this many MORE per arm, once"):
    python scripts/run_stage1.py --task binpacking --generations 5

The real Week 3 experiment (matched arms, multi-day, resumable):
    python scripts/run_stage1.py --task circle_packing \\
        --conditions single_winner,elite_band --band-size 3 \\
        --seeds 0,1000,2000 --target-generations 100 \\
        --ledger runs/week3.db --daily-token-cap 180000

--target-generations N is a TOTAL per arm (an arm is one condition x one
seed). Re-running the identical command on later days continues each arm
until it reaches N and then does nothing more -- unlike --generations, which
always means "N more". Arms advance ROUND-ROBIN in chunks of --round-size
generations, so if the daily Sigma quota runs out mid-day every arm is at
(nearly) the same generation count. A cut-short experiment is therefore still
a MATCHED experiment, which is what the elite-band-vs-single-winner ablation
needs ("cut scope, not the cap": research-program-guide §1.4).

Needs:
  - GROQ_API_KEY in the environment (never on the command line).
  - A real Docker daemon (see WEEK2_SETUP.md); evaluate() runs a container
    per candidate.
  - Pass --restart to archive an arm's existing ledger+checkpoint (renamed
    *.bak-<timestamp>, never deleted) and start it over from P_0.

Exit codes: 0 done / target reached, 1 halted (integrity violation or
control channel), 2 configuration or ledger-chain error, 3 Sigma budget hit
(re-run later), 4 no progress (a bug -- please report).
"""

import argparse
import json
import platform
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from delta import checkpoint as checkpoint_mod  # noqa: E402
from delta.admission.tasks import get_task  # noqa: E402
from delta.control.channel import ControlChannel  # noqa: E402
from delta.evaluation.launcher import PINNED_IMAGE  # noqa: E402
from delta.integrity import manifest as manifest_mod  # noqa: E402
from delta.ledger.chain import Ledger  # noqa: E402
from delta.loop import run_generations  # noqa: E402
from sigma.budget import BudgetExceeded  # noqa: E402
from sigma.client import DEFAULT_DAILY_REQUEST_CAP, SigmaClient, SigmaError, SigmaProposalError  # noqa: E402
from sigma.prompts import PROMPT_VERSION, prompt_fingerprint  # noqa: E402

CONDITIONS = ("single_winner", "elite_band")

# `git_dirty` in runmeta.json answers "was the code that produces results
# identical to the recorded commit?" -- so it only looks at run-affecting
# paths. Editing STATUS.md / DRAFT.md / analysis scripts between days (which
# the workflow does daily) must not make every later invocation look dirty.
RUN_CODE_PATHS = ["delta", "harness", "sigma", "seed", "scripts/run_stage1.py"]


@dataclass(frozen=True)
class Arm:
    condition: str
    seed_base: int
    band_size: int
    ledger_path: str

    @property
    def label(self) -> str:
        return f"{self.condition}/seed{self.seed_base}"


# --- pure helpers (unit-tested; no network, no Docker) ------------------------

def _ledger_path_for_seed(base_path: str, seed_base: int, multi: bool) -> str:
    if not multi:
        return base_path
    p = Path(base_path)
    return str(p.with_name(f"{p.stem}.seed{seed_base}{p.suffix}"))


def _arm_ledger_path(base_path: str, condition: str, seed_base: int) -> str:
    p = Path(base_path)
    return str(p.with_name(f"{p.stem}.{condition}.seed{seed_base}{p.suffix}"))


def build_arms(conditions: list[str], seed_bases: list[int], band_size: int, base_ledger: str) -> list[Arm]:
    """Seed-major order, so paired arms (same seed, different condition) are
    adjacent and always advance together."""
    legacy = list(conditions) == ["single_winner"]
    arms = []
    for seed in seed_bases:
        for cond in conditions:
            path = (
                _ledger_path_for_seed(base_ledger, seed, multi=len(seed_bases) > 1)
                if legacy else _arm_ledger_path(base_ledger, cond, seed)
            )
            arms.append(Arm(cond, seed, 1 if cond == "single_winner" else band_size, path))
    return arms


def plan_round(arms, done: dict, target: int, round_size: int) -> list:
    """One round-robin pass: [(arm, n_generations_this_chunk)] for every arm
    still below target. Empty list == everything finished."""
    return [(a, min(round_size, target - done[a])) for a in arms if done[a] < target]


def run_batch(arms, *, target, round_size, legacy_generations, done_fn, run_arm_fn) -> int:
    """Drive arms round-robin. target=None is the legacy single pass of
    `legacy_generations` per arm. Stops the WHOLE batch on a budget stop
    (code 3): Sigma's cap is process-wide, and continuing to feed later arms
    would unbalance them."""
    while True:
        if target is None:
            plan = [(a, legacy_generations) for a in arms]
        else:
            plan = plan_round(arms, {a: done_fn(a) for a in arms}, target, round_size)
        if not plan:
            return 0
        before = sum(done_fn(a) for a in arms)
        for arm, n in plan:
            code = run_arm_fn(arm, n)
            if code != 0:
                return code
        if target is None:
            return 0
        if sum(done_fn(a) for a in arms) <= before:
            print("!!! a full round made no progress -- refusing to loop forever.", file=sys.stderr)
            return 4


def _generations_done(arm: Arm) -> int:
    ckpt = checkpoint_mod.load(checkpoint_mod.default_path_for_ledger(Path(arm.ledger_path)))
    return ckpt.next_generation_index if ckpt else 0


def _archive_existing(arm: Arm) -> None:
    stamp = time.strftime("%Y%m%dT%H%M%S")
    for path in (Path(arm.ledger_path), checkpoint_mod.default_path_for_ledger(Path(arm.ledger_path))):
        if path.exists():
            dest = path.with_name(path.name + f".bak-{stamp}")
            path.rename(dest)
            print(f"archived {path} -> {dest}")


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, timeout=10)
        return out.stdout.strip() if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def _write_run_meta(base_ledger: str, args, arms, model: str) -> None:
    """Append one record per invocation to <ledger stem>.runmeta.json. The
    per-invocation git commit is how the paper can state that the Delta code
    was identical across every day of the run (or say plainly that it was
    not). 'Dirty' = a tracked run-affecting file (RUN_CODE_PATHS) differs
    from the recorded commit; docs and analysis scripts do not count."""
    path = Path(base_ledger).with_suffix(".runmeta.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        meta = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        meta = {"task": args.task, "model": model, "image_digest": PINNED_IMAGE, "invocations": []}
    meta["invocations"].append({
        "ts_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "git_commit": _git("rev-parse", "HEAD"),
        "git_dirty": bool(_git("status", "--porcelain", "--untracked-files=no", "--", *RUN_CODE_PATHS)),
        "prompt_version": PROMPT_VERSION,
        "prompt_sha256": prompt_fingerprint(),
        "python": platform.python_version(),
        "image_digest": PINNED_IMAGE,
        "args": {k: v for k, v in vars(args).items()},
        "arms": [a.label for a in arms],
    })
    path.write_text(json.dumps(meta, indent=2))


# --- one chunk of one arm (needs real Docker + Sigma) --------------------------

def run_one_arm(arm: Arm, generations: int, *, task_name: str, sigma: SigmaClient, verbose: bool) -> int:
    task = get_task(task_name)
    ledger = Ledger(arm.ledger_path)
    control = ControlChannel()
    manifest_roots = [REPO_ROOT / "delta", REPO_ROOT / "harness"]
    work_root = REPO_ROOT / "work"
    work_root.mkdir(exist_ok=True)

    ckpt_path = checkpoint_mod.default_path_for_ledger(Path(arm.ledger_path))
    ckpt = checkpoint_mod.load(ckpt_path)
    if ckpt is not None and ckpt.task_name != task_name:
        print(f"!!! checkpoint {ckpt_path} is for task={ckpt.task_name!r}, not {task_name!r} "
              f"-- use a different --ledger or --restart.", file=sys.stderr)
        ledger.close()
        return 2
    if ckpt is not None and ckpt.band_size != arm.band_size:
        print(f"!!! checkpoint {ckpt_path} was written with band_size={ckpt.band_size}, this arm wants "
              f"{arm.band_size}. Changing k mid-run would corrupt the ablation -- --restart or fix the flag.",
              file=sys.stderr)
        ledger.close()
        return 2
    resume = {}
    if ckpt is not None:
        resume = dict(
            start_generation_index=ckpt.next_generation_index, initial_parent_src=ckpt.parent_src,
            initial_parent_id=ckpt.parent_id, initial_best_fitness=ckpt.best_fitness, initial_band=ckpt.band,
        )
    start = ckpt.next_generation_index if ckpt else 0

    exit_code, summary = 0, None
    try:
        summary = run_generations(
            task=task, n_generations=generations, ledger=ledger, work_root=work_root,
            manifest_roots=manifest_roots, sigma=sigma, control=control, seed_base=arm.seed_base,
            checkpoint_path=ckpt_path, stop_exceptions=(BudgetExceeded,),
            retry_exceptions=(SigmaProposalError,), band_size=arm.band_size,
            evaluate_baseline=True, **resume,
        )
    except manifest_mod.IntegrityViolation as e:
        print(f"\n!!! INTEGRITY VIOLATION -- HALTING: {e}", file=sys.stderr)
        print("Delta itself changed during this run. Do not trust anything after the last "
              "known-good ledger record (Phase1 guide §5: not a recoverable error).", file=sys.stderr)
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
    if summary is None:
        return exit_code

    outcomes = [g.outcome for g in summary.generations]
    end = start + len(summary.generations)
    base = f" baseline={summary.baseline_fitness}" if summary.baseline_fitness is not None else ""
    print(f"[{arm.label}] gens {start}-{end - 1 if outcomes else start}: "
          f"{outcomes.count('improved')} improved / {outcomes.count('kept')} kept / "
          f"{outcomes.count('stalled')} stalled | best={summary.best_fitness}{base} | "
          f"Sigma today: {sigma.budget.daily_cap - sigma.budget.remaining()} req, "
          f"{sigma.budget.tokens_used()} tok")
    if verbose:
        for g in summary.generations:
            print(f"    gen {g.generation_index}: {g.outcome:8s} clone={g.clone_id} fitness={g.fitness}")
    if summary.stopped_reason == "BudgetExceeded":
        print(f"\nSigma budget stop: {summary.stopped_detail}\n"
              f"Checkpoint saved. Re-run this exact command after the provider's reset.", file=sys.stderr)
        return 3
    return exit_code


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--task", default="binpacking", choices=["binpacking", "circle_packing"])
    ap.add_argument("--generations", type=int, default=None,
                    help="LEGACY/smoke-test mode: attempt this many MORE generations per arm, once. "
                         "Default 5 if --target-generations is not given.")
    ap.add_argument("--target-generations", type=int, default=None,
                    help="TOTAL generations per arm (condition x seed). Re-running continues until every "
                         "arm reaches it. Arms advance round-robin in --round-size chunks.")
    ap.add_argument("--round-size", type=int, default=10, help="generations per arm per round-robin chunk")
    ap.add_argument("--conditions", default="single_winner",
                    help="comma-separated subset of: " + ", ".join(CONDITIONS))
    ap.add_argument("--band-size", type=int, default=3, help="k for the elite_band condition (>=2)")
    ap.add_argument("--seed-base", type=int, default=0, help="ignored if --seeds is given")
    ap.add_argument("--seeds", default=None, help="comma-separated seed bases, e.g. 0,1000,2000")
    ap.add_argument("--ledger", default=str(REPO_ROOT / "run_ledger.db"),
                    help="base path; each arm derives its own ledger + checkpoint from it")
    ap.add_argument("--restart", action="store_true",
                    help="archive each arm's existing ledger+checkpoint (renamed, never deleted) and start over")
    ap.add_argument("--daily-request-cap", type=int, default=DEFAULT_DAILY_REQUEST_CAP)
    ap.add_argument("--daily-token-cap", type=int, default=None,
                    help="local tokens/day cap, set a margin BELOW the provider's real limit "
                         "(measure first with scripts/usage_report.py)")
    ap.add_argument("--verbose", action="store_true", help="print every generation, not just per-chunk summaries")
    args = ap.parse_args()

    if args.generations is not None and args.target_generations is not None:
        ap.error("--generations and --target-generations are mutually exclusive")
    conditions = [c.strip() for c in args.conditions.split(",") if c.strip()]
    bad = [c for c in conditions if c not in CONDITIONS]
    if bad or not conditions:
        ap.error(f"--conditions must be drawn from {CONDITIONS}, got {args.conditions!r}")
    if "elite_band" in conditions and args.band_size < 2:
        ap.error("--band-size must be >= 2 for elite_band (k=1 IS single_winner)")
    if args.round_size < 1:
        ap.error("--round-size must be >= 1")

    seed_bases = [int(s) for s in args.seeds.split(",")] if args.seeds else [args.seed_base]
    arms = build_arms(conditions, seed_bases, args.band_size, args.ledger)

    try:
        sigma = SigmaClient(daily_request_cap=args.daily_request_cap, daily_token_cap=args.daily_token_cap)
    except SigmaError as e:
        print(f"!!! {e}", file=sys.stderr)
        return 2

    if args.restart:
        for a in arms:
            _archive_existing(a)
    _write_run_meta(args.ledger, args, arms, sigma.model)

    print(f"task={args.task} model={sigma.model} arms={[a.label for a in arms]}")
    print(f"mode={'target ' + str(args.target_generations) + ' total/arm, round-robin x' + str(args.round_size) if args.target_generations else 'legacy ' + str(args.generations or 5) + ' more/arm'}")
    print(f"Sigma today: {sigma.budget.daily_cap - sigma.budget.remaining()}/{sigma.budget.daily_cap} req, "
          f"{sigma.budget.tokens_used()} tok"
          + (f" (local token cap {args.daily_token_cap})" if args.daily_token_cap else " (NO local token cap)"))

    code = run_batch(
        arms, target=args.target_generations, round_size=args.round_size,
        legacy_generations=args.generations if args.generations is not None else 5,
        done_fn=_generations_done,
        run_arm_fn=lambda arm, n: run_one_arm(arm, n, task_name=args.task, sigma=sigma, verbose=args.verbose),
    )
    if code == 0 and args.target_generations:
        print(f"\nAll {len(arms)} arm(s) reached {args.target_generations} generations. "
              f"Summarize with: python scripts/summarize_ledgers.py {Path(args.ledger).parent}/*.db")
    elif code == 3:
        print("Stopping the whole batch (budget is process-wide). Arms are matched to within one chunk.",
              file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
