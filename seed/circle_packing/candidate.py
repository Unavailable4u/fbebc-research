# seed/circle_packing/candidate.py
#
# Primary task (research-program-guide §1.2, week 3 — the one that's
# reported). Maximize the sum of radii of n non-overlapping circles packed
# inside a unit square. Deliberately the same task AlphaEvolve showcased
# publicly (n=26), for a recognizable-to-reviewers reference point. Not a
# claim of beating AlphaEvolve's result — this validates the governance
# mechanism on a task the field already recognizes, at a much smaller
# compute budget, per §1.2's explicit honesty note.
#
# CONTRACT (verified by G2 / contracts.verify_contract; do not alter):
#   - signature and annotations are fixed
#   - imports live outside the block (candidates cannot add imports)

from __future__ import annotations
import math

# ── IMMUTABLE BOILERPLATE (Delta-managed) ──────────────────────────────
# Any edit to this region causes immediate rejection.

# EVOLVE-BLOCK-START: circle_packing
def candidate_packing(n: int) -> list[tuple[float, float, float]]:
    """Return n (x, y, r) tuples: circle centers and radii, all inside
    the unit square [0,1]x[0,1], pairwise non-overlapping.
    CONTRACT: signature fixed. Return exactly n tuples.
    """
    # Generation-0 seed: naive grid placement, small fixed radius.
    side = math.ceil(math.sqrt(n))
    r = 1.0 / (2 * side)
    out = []
    for i in range(n):
        x = (i % side + 0.5) * (1.0 / side)
        y = (i // side + 0.5) * (1.0 / side)
        out.append((x, y, r))
    return out
# EVOLVE-BLOCK-END: circle_packing
