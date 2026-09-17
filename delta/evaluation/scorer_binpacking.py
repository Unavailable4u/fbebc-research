# delta/evaluation/scorer_binpacking.py
#
# Warm-up task scorer (research-program-guide §1.2). Correctness-only
# fitness per Stage 1 scope (§1.1): no latency, no oracle needed beyond
# validating capacity constraints and full item coverage. Fitness convention
# kept consistent with score_packing (higher is better), so fitness here is
# defined as -bins_used: fewer bins is a higher (less negative) score.

def score_binpacking(instance: dict, solution: list[int]) -> dict:
    items = instance["items"]
    capacity = instance["capacity"]

    if not isinstance(solution, list) or len(solution) != len(items):
        return {"fitness": None, "valid": False, "reason": "wrong_count"}

    bins: dict[int, float] = {}
    for item_size, bin_idx in zip(items, solution):
        if not isinstance(bin_idx, int) or bin_idx < 0:
            return {"fitness": None, "valid": False, "reason": "invalid_bin_index"}
        bins[bin_idx] = bins.get(bin_idx, 0.0) + item_size
        if bins[bin_idx] > capacity + 1e-9:
            return {"fitness": None, "valid": False, "reason": "capacity_exceeded"}

    bins_used = len(bins)
    return {"fitness": -float(bins_used), "valid": True, "bins_used": bins_used}


def make_fixed_instance_set(seed: int = 0, n_instances: int = 5) -> list[dict]:
    """Small, fixed, host-generated instance set — identical across all
    candidates in a generation (§10's determinism requirement)."""
    import random

    rng = random.Random(seed)
    instances = []
    for i in range(n_instances):
        n_items = rng.randint(8, 20)
        items = [round(rng.uniform(1, 10), 3) for _ in range(n_items)]
        instances.append({
            "instance_id": f"bp-{i:04d}",
            "items": items,
            "capacity": 15.0,
        })
    return instances
