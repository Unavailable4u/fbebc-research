# delta/checkpoint.py
#
# Week 3 Day 16-20 gap: a single circle_packing run's call budget (~1,000
# Sigma calls per research-program-guide §1.5) does not fit inside one
# day's free-tier request cap (sigma/budget.py's conservative default is
# 900/day). A real Week 3 run must therefore be invoked once (or a few
# times) per day across several days and pick up exactly where the
# previous invocation left off -- see WEEK3_SETUP.md.
#
# This is a deliberately separate, explicit checkpoint file, NOT an
# attempt to reconstruct resume state by replaying the ledger. The ledger
# is the durable, verified record of what happened, but it does not store
# `valid` or the candidate's actual source text (only a digest) -- both
# are needed to resume a hill-climbing run correctly, and re-deriving them
# from what the ledger *does* store would mean re-implementing loop.py's
# adoption rule a second time in a different place, with a second chance
# to get it subtly wrong. Instead, run_generations() (delta/loop.py) is
# the only code that ever writes a checkpoint, immediately after making
# each live adoption decision -- so the checkpoint can never disagree with
# the decision that produced it.
#
# This file is intentionally not part of the ledger's hash chain: it is
# resume convenience, not a provenance claim. The paper's integrity claims
# rest on the ledger (delta/ledger/chain.py), not on this file.

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class RunCheckpoint:
    task_name: str
    seed_base: int
    next_generation_index: int
    # For a single-winner run (band_size == 1) these three describe the
    # incumbent. For an elite-band run they describe the band's BEST member,
    # kept only for at-a-glance inspection and backward compatibility --
    # `band` below is the authoritative resume state.
    parent_src: str
    parent_id: str | None
    best_fitness: float | None
    # Added Week 3 Day 16 (elite-band ablation). Defaults keep every
    # pre-existing checkpoint file (which lacks these keys) loadable: a
    # missing `band` means "reconstruct a one-member band from parent_*".
    band_size: int = 1
    band: list[dict] | None = None  # delta.selection.Elite rows, ORDER PRESERVED


def save(path: Path, ckpt: RunCheckpoint) -> None:
    """Atomic on POSIX (rename is a single syscall) so a process killed
    mid-save leaves either the old checkpoint or the new one, never a
    truncated/corrupt file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(asdict(ckpt)), encoding="utf-8")
    tmp.replace(path)


def load(path: Path) -> RunCheckpoint | None:
    path = Path(path)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return RunCheckpoint(**data)


def default_path_for_ledger(ledger_path: Path) -> Path:
    ledger_path = Path(ledger_path)
    return ledger_path.with_suffix(ledger_path.suffix + ".checkpoint.json")
