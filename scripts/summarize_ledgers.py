#!/usr/bin/env python3
"""scripts/summarize_ledgers.py -- read-only progress / results summary.

    python scripts/summarize_ledgers.py runs/week3.*.db

For each arm's ledger: chain check, generations, Sigma calls per generation
(the measured number the call-budget math needs), P_0 baseline vs best,
running best at checkpoints, sandbox-status counts, and the rejection
taxonomy. Then, if both conditions are present, a matched-generation
comparison per seed.

Statistical honesty (paper guide §5): the comparison prints INDIVIDUAL
per-seed values side by side, never a mean +/- sd and never a p-value. With
3 seeds that is all the data supports.

Opens ledgers read-only (sqlite URI mode=ro); never modifies anything.
"""

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def read_rows(path: str) -> list[dict]:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute("SELECT * FROM records ORDER BY seq")]
    finally:
        con.close()


def verify_chain_rows(rows: list[dict]) -> bool:
    """Same check as delta.ledger.chain.Ledger.verify_chain, run over rows
    already loaded through the read-only connection. Deliberately does NOT
    instantiate Ledger: its constructor switches the DB to WAL mode and runs
    the schema script (and would create an empty DB on a mistyped path), so
    using it here would make "read-only" untrue."""
    import hashlib

    from delta.ledger.chain import GENESIS, _canon

    prev = GENESIS
    for rec in rows:
        if rec["prev_digest"] != prev:
            return False
        if hashlib.sha256(prev.encode() + _canon(rec)).hexdigest() != rec["digest"]:
            return False
        prev = rec["digest"]
    return True


def analyze(rows: list[dict]) -> dict:
    """Pure function of the ledger rows -- unit tested."""
    task = rows[0]["task"] if rows else None
    base = next((r for r in rows if r["generation_index"] == -1 and r["attested"] and r["fitness"] is not None), None)
    gen_rows = [r for r in rows if r["generation_index"] >= 0]
    gens = sorted({r["generation_index"] for r in gen_rows})
    evaluated = [r for r in gen_rows if r["admitted"] == 1]
    rejections: dict[str, int] = {}
    for r in gen_rows:
        if r["rejection_class"]:
            rejections[r["rejection_class"]] = rejections.get(r["rejection_class"], 0) + 1
    status: dict[str, int] = {}
    for r in evaluated:
        status[r["status"]] = status.get(r["status"], 0) + 1
    # ledger stores `fitness` but not `valid`; for circle_packing every valid
    # packing has fitness > 0, so "ran fine, scored 0.0" == invalid packing.
    invalid = sum(1 for r in evaluated if task == "circle_packing" and r["status"] == "ok" and r["fitness"] == 0.0)

    # running best (attested candidates only -- unattested never enter selection)
    best_by_gen: dict[int, float] = {}
    running = base["fitness"] if base else None
    for g in gens:
        for r in (x for x in gen_rows if x["generation_index"] == g and x["attested"] and x["fitness"] is not None):
            if running is None or r["fitness"] > running:
                running = r["fitness"]
        best_by_gen[g] = running
    seed_base = None
    for r in gen_rows:
        seed_base = r["seed"] - r["generation_index"]
        break
    if seed_base is None and base:
        seed_base = base["seed"]
    label = next((r["ablation_config"] for r in rows if r["ablation_config"]), None)
    return {
        "task": task, "label": label, "seed_base": seed_base,
        "baseline": base["fitness"] if base else None,
        "n_generations": len(gens), "n_calls": len(gen_rows),
        "calls_per_gen": (len(gen_rows) / len(gens)) if gens else None,
        "n_evaluated": len(evaluated), "n_unattested": sum(1 for r in evaluated if not r["attested"]),
        "status": status, "invalid_packings": invalid, "rejections": rejections,
        "best_by_gen": best_by_gen, "best": running,
    }


def best_at(a: dict, n_gens: int):
    """Best fitness after the first n_gens generations (n_gens=0 -> baseline)."""
    if n_gens <= 0:
        return a["baseline"]
    keys = [g for g in a["best_by_gen"] if g < n_gens]
    return a["best_by_gen"][max(keys)] if keys else a["baseline"]


def _fmt(x):
    return "n/a" if x is None else f"{x:.4f}" if isinstance(x, float) else str(x)


def checkpoints(n: int) -> list[int]:
    pts = sorted({p for p in (1, 5, 10, 25, 50, 100, 200, 400, 800) if p < n} | {n})
    return pts


def print_arm(path: str, a: dict) -> None:
    print(f"== {path}")
    print(f"   arm: {a['label']} | task: {a['task']} | seed_base: {a['seed_base']}")
    cpg = f"{a['calls_per_gen']:.2f}" if a["calls_per_gen"] else "n/a"
    print(f"   generations: {a['n_generations']} | Sigma replies logged: {a['n_calls']} ({cpg} per generation)")
    if a["baseline"] is not None and a["best"] is not None:
        d = a["best"] - a["baseline"]
        pct = f", {100 * d / a['baseline']:+.1f}%" if a["baseline"] else ""
        print(f"   P_0 baseline: {_fmt(a['baseline'])} | best: {_fmt(a['best'])} ({d:+.4f}{pct})")
    else:
        print(f"   P_0 baseline: {_fmt(a['baseline'])} | best: {_fmt(a['best'])}")
    if a["n_generations"]:
        print("   best after N gens: " + "  ".join(f"{n}:{_fmt(best_at(a, n))}" for n in checkpoints(a["n_generations"])))
    print(f"   evaluated: {a['n_evaluated']} | unattested: {a['n_unattested']} | sandbox status: {a['status'] or '{}'}"
          + (f" | scored-invalid packings: {a['invalid_packings']}" if a["task"] == "circle_packing" else ""))
    rej = ", ".join(f"{k} {v}" for k, v in sorted(a["rejections"].items(), key=lambda kv: -kv[1])) or "none"
    print(f"   rejections: {rej}")


def print_comparison(arms: dict) -> None:
    by_seed: dict = {}
    for path, a in arms.items():
        by_seed.setdefault(a["seed_base"], {})[a["label"]] = a
    common = min((a["n_generations"] for a in arms.values()), default=0)
    print(f"\n== matched-generation comparison @ {common} generations (the fewest any arm has completed)")
    labels = sorted({a["label"] for a in arms.values() if a["label"]})
    print("   seed      " + "  ".join(f"{l:>18}" for l in labels))
    for seed in sorted(by_seed, key=lambda s: (s is None, s)):
        cells = [_fmt(best_at(by_seed[seed][l], common)) if l in by_seed[seed] else "-" for l in labels]
        print(f"   {str(seed):9} " + "  ".join(f"{c:>18}" for c in cells))
    print("   (individual seeds only -- no mean/sd/p-value; see paper guide §5)")


def print_runmeta(paths: list[str]) -> None:
    seen = set()
    for p in paths:
        meta = Path(p).with_name(Path(p).name.split(".")[0] + ".runmeta.json")
        if meta in seen or not meta.exists():
            continue
        seen.add(meta)
        m = json.loads(meta.read_text())
        commits = [i.get("git_commit") for i in m["invocations"]]
        dirty = sum(1 for i in m["invocations"] if i.get("git_dirty"))
        print(f"\n== run metadata ({meta.name}): model={m.get('model')} invocations={len(commits)} "
              f"distinct git commits={len(set(commits))} ({', '.join(sorted({(c or '?')[:8] for c in commits}))}) "
              f"dirty invocations={dirty}")
        print(f"   image: {m.get('image_digest')}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ledgers", nargs="+", help="ledger .db files (shell globs are fine)")
    args = ap.parse_args()
    paths = [p for p in args.ledgers if re.search(r"\.db$", p)]
    if not paths:
        print("no .db ledger paths given", file=sys.stderr)
        return 2
    arms = {}
    for p in sorted(paths):
        try:
            rows = read_rows(p)
        except sqlite3.Error as e:
            print(f"== {p}: cannot read ({e})")
            continue
        a = analyze(rows)
        chain = "OK" if verify_chain_rows(rows) else "FAILED"
        print_arm(p, a)
        print(f"   ledger chain: {chain}")
        if a["n_generations"] or a["baseline"] is not None:
            arms[p] = a
    if len({a["label"] for a in arms.values()}) > 1:
        print_comparison(arms)
    print_runmeta(paths)
    return 0


if __name__ == "__main__":
    sys.exit(main())
