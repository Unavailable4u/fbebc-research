#!/usr/bin/env python3
"""scripts/replay_selection.py -- did the node-type-only duplicate key change any results?

    python scripts/replay_selection.py runs/week3.*.db

Background: selection originally rejected a child as a "duplicate" when its
semantic_fingerprint matched a band member's. That fingerprint hashes only AST
node TYPES, so two programs differing only in numeric constants or names looked
identical -- and a constant-tuned child was rejected even when strictly fitter.
The corrected rule keys on exact_fingerprint (full canonical AST).

For each arm this replays the ledger's candidates, in order, through two copies
of the selection rule -- one keyed the OLD way (what the run actually used), one
keyed the NEW way -- and reports whether they ever disagree.

  * If the OLD-key replay reproduces the arm's checkpoint band, the replay is
    faithful, and any disagreement is a real effect on the run.
  * If the two never disagree, the pre-fix history is IDENTICAL under the
    corrected rule and continuing after the fix is clean.

Read-only: ledgers are opened mode=ro; candidate source files are read as TEXT
and never executed (never run LLM-written code outside the sandbox).
"""

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from delta.admission.metrics import exact_fingerprint  # noqa: E402
from delta.selection import Elite, EliteBand  # noqa: E402


def band_size_from_label(label: str | None) -> int:
    m = re.search(r"_k(\d+)$", label or "")
    return int(m.group(1)) if m else 1


def replay(rows: list[dict], read_src, k: int) -> dict:
    """Pure function over ledger rows (unit-tested). `read_src(clone_id)` returns
    the candidate's source text or None. A candidate is considered by selection
    iff it was attested and scored valid (circle_packing: fitness > 0 -- invalid
    packings are stored with fitness 0.0)."""
    old, new = EliteBand(k), EliteBand(k)
    blocked, missing, considered = [], 0, 0
    first_divergence = None
    for r in rows:
        if not (r["admitted"] == 1 and r["attested"] == 1 and r["fitness"] is not None and r["fitness"] > 0):
            continue
        src = read_src(r["clone_id"])
        if src is None:
            missing += 1
        new_key = None
        if src is not None:
            try:
                new_key = exact_fingerprint(src)
            except SyntaxError:
                new_key = None
        old_best = old.best().fitness if old.best() else None
        e_old = old.consider(Elite(src="", clone_id=r["clone_id"], fitness=r["fitness"], fingerprint=r["semantic_fingerprint"]))
        e_new = new.consider(Elite(src="", clone_id=r["clone_id"], fitness=r["fitness"], fingerprint=new_key))
        if r["generation_index"] >= 0:
            considered += 1
        if e_new and not e_old:
            if first_divergence is None:
                first_divergence = r["generation_index"]
            blocked.append({
                "gen": r["generation_index"], "fitness": r["fitness"],
                "strict_improvement": old_best is not None and r["fitness"] > old_best + 1e-9,
                "gain": (r["fitness"] - old_best) if old_best is not None else None,
            })
    ob, nb = old.best(), new.best()
    return {
        "k": k, "considered": considered, "missing_sources": missing,
        "blocked": blocked, "first_divergence": first_divergence,
        "old_best": ob.fitness if ob else None, "new_best": nb.fitness if nb else None,
        "old_band": sorted(e.fitness for e in old.elites), "new_band": sorted(e.fitness for e in new.elites),
    }


def _read_rows(path: str) -> list[dict]:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute("SELECT * FROM records ORDER BY seq")]
    finally:
        con.close()


def _checkpoint_band(ledger_path: str):
    ck = Path(ledger_path + ".checkpoint.json")
    if not ck.exists():
        return None
    data = json.loads(ck.read_text())
    return sorted(e["fitness"] for e in (data.get("band") or []))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ledgers", nargs="+")
    ap.add_argument("--work", default=str(REPO_ROOT / "work"), help="dir holding <clone_id>/candidate.py")
    args = ap.parse_args()

    def read_src(clone_id: str):
        p = Path(args.work) / clone_id / "candidate.py"
        return p.read_text() if p.exists() else None

    any_diverged, any_unfaithful = False, False
    for path in sorted(p for p in args.ledgers if p.endswith(".db")):
        rows = _read_rows(path)
        label = next((r["ablation_config"] for r in rows if r["ablation_config"]), None)
        res = replay(rows, read_src, band_size_from_label(label))
        ck = _checkpoint_band(path)
        faithful = None if ck is None else (ck == res["old_band"])
        any_unfaithful |= (faithful is False)
        print(f"== {path}  [{label}]")
        print(f"   candidates considered: {res['considered']} | source files missing: {res['missing_sources']}")
        print(f"   replay of the rule AS RUN reproduces the checkpoint band: "
              f"{'n/a (no checkpoint)' if faithful is None else 'YES' if faithful else 'NO  <-- replay not trustworthy for this arm'}")
        if res["blocked"]:
            any_diverged = True
            si = [b for b in res["blocked"] if b["strict_improvement"]]
            print(f"   !! DIVERGES from generation {res['first_divergence']}: {len(res['blocked'])} candidate(s) "
                  f"were rejected as 'duplicates' but differ from every band member (constants/names) "
                  f"-- {len(si)} of them strictly better than the band's best "
                  f"(gains: {', '.join(f'+{b['gain']:.4f}' for b in si) or 'none'})")
        else:
            print("   no divergence: corrected rule makes identical decisions on this arm's history")
        print(f"   best fitness: as run {res['old_best']} | under corrected rule {res['new_best']}")
    print()
    if any_unfaithful:
        print("VERDICT: at least one replay did not reproduce its checkpoint -- do not rely on this output until that is explained.")
        return 2
    print("VERDICT: " + ("history DIFFERS under the corrected rule (see !! lines) -- decide restart vs. disclosed mid-run fix."
                         if any_diverged else
                         "NO arm diverges -- everything run so far is identical under the corrected rule; a mid-run fix is clean."))
    return 0


if __name__ == "__main__":
    sys.exit(main())
