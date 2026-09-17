# delta/evaluation/scorer_circle_packing.py
#
# Verbatim from research-program-guide §1.2. Correctness gate + fitness in
# one function, no oracle needed: the objective *is* the fitness.

def score_packing(circles: list[tuple[float, float, float]], n: int) -> dict:
    if len(circles) != n:
        return {"fitness": 0.0, "valid": False, "reason": "wrong_count"}
    for x, y, r in circles:
        if r <= 0 or x - r < -1e-9 or x + r > 1 + 1e-9 or y - r < -1e-9 or y + r > 1 + 1e-9:
            return {"fitness": 0.0, "valid": False, "reason": "out_of_bounds"}
    for i in range(len(circles)):
        for j in range(i + 1, len(circles)):
            x1, y1, r1 = circles[i]
            x2, y2, r2 = circles[j]
            if (x1 - x2) ** 2 + (y1 - y2) ** 2 < (r1 + r2) ** 2 - 1e-9:
                return {"fitness": 0.0, "valid": False, "reason": "overlap"}
    return {"fitness": sum(r for _, _, r in circles), "valid": True}
