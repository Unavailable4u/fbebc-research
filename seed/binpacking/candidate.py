# seed/binpacking/candidate.py
#
# Warm-up task (research-program-guide §1.2, week 1-2): improve a bin-packing
# heuristic. Given a list of item sizes and a bin capacity, evolve a function
# that assigns items to bins. Score (host-side) = number of bins used, lower
# is better, on a small fixed instance set. Exists purely to shake pipeline
# bugs out before spending real experiment budget on circle packing. NOT
# reported in the paper.
#
# CONTRACT (verified by G2 / contracts.verify_contract; do not alter):
#   - signature and annotations are fixed
#   - imports live outside the block (candidates cannot add imports)
#   - the RNG is injected, not constructed (host decision, per Phase1 guide §4.2)

from __future__ import annotations

# ── IMMUTABLE BOILERPLATE (Delta-managed) ──────────────────────────────
# Any edit to this region causes immediate rejection.

# EVOLVE-BLOCK-START: binpacking_core
def candidate_solver(instances: list[dict], rng) -> list[dict]:
    """Generation-0 seed: naive first-fit decreasing.

    Each instance: {"instance_id": str, "items": list[float], "capacity": float}.
    Return one result dict per instance:
      {"instance_id": str, "solution": list[int]}
    where solution[i] is the bin index assigned to items[i].

    CONTRACT (verified by Delta; do not alter):
      - signature and annotations are fixed
      - len(return) == len(instances)
      - each element: {"instance_id": str, "solution": list[int]}
      - no I/O, no imports beyond the module header, no global mutation
    """
    out = []
    for inst in instances:
        items = list(inst["items"])
        capacity = inst["capacity"]
        # First-fit decreasing: sort largest-first, drop into first bin that fits.
        order = sorted(range(len(items)), key=lambda i: items[i], reverse=True)
        bin_loads: list[float] = []
        assignment = [0] * len(items)
        for idx in order:
            size = items[idx]
            placed = False
            for b, load in enumerate(bin_loads):
                if load + size <= capacity:
                    bin_loads[b] += size
                    assignment[idx] = b
                    placed = True
                    break
            if not placed:
                bin_loads.append(size)
                assignment[idx] = len(bin_loads) - 1
        out.append({"instance_id": inst["instance_id"], "solution": assignment})
    return out
# EVOLVE-BLOCK-END: binpacking_core
