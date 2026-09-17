# delta/admission/tasks.py
#
# Stage 1 task registry (research-program-guide §1.2):
#   - "binpacking": warm-up task, weeks 1-2, pipeline debugging only,
#     NOT reported in the paper.
#   - "circle_packing": primary task, week 3, the one that's reported.
#
# Each task pins the EVOLVE-BLOCK entry-point function name(s) that G2
# (contracts.verify_contract) checks for signature/annotation stability.

from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class TaskSpec:
    name: str
    seed_path: Path
    pinned_names: frozenset[str]
    block_name: str


TASKS: dict[str, TaskSpec] = {
    "binpacking": TaskSpec(
        name="binpacking",
        seed_path=REPO_ROOT / "seed" / "binpacking" / "candidate.py",
        pinned_names=frozenset({"candidate_solver"}),
        block_name="binpacking_core",
    ),
    "circle_packing": TaskSpec(
        name="circle_packing",
        seed_path=REPO_ROOT / "seed" / "circle_packing" / "candidate.py",
        pinned_names=frozenset({"candidate_packing"}),
        block_name="circle_packing",
    ),
}


def get_task(name: str) -> TaskSpec:
    if name not in TASKS:
        raise KeyError(f"unknown task {name!r}; known tasks: {sorted(TASKS)}")
    return TASKS[name]
