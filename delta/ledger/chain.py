# delta/ledger/chain.py
#
# Ported from the Phase1 implementation guide, §11. Logic is unchanged
# (append computes prev-chained SHA-256 digest; verify_chain walks and
# recomputes every digest); only the CHAINED field list and schema.sql
# reflect Stage 1's reduced column set (see schema.sql's module docstring).
#
# One robustness fix vs. the guide's literal listing: the guide hardcodes
# the schema path as the string "delta/ledger/schema.sql", which only
# resolves if the process cwd happens to be the repo root. This version
# resolves it relative to this file instead, so tests and real runs behave
# the same regardless of cwd.

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

GENESIS = "0" * 64
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"

# Fields that go into the hash chain. Mirrors Phase1 §11's own CHAINED
# selection: lineage + admission + core evaluation + integrity fields are
# chained; verbose/debug fields (stderr_tail) are not, since they carry no
# claim the paper depends on and chaining them would make the ledger
# needlessly brittle to harmless logging changes.
CHAINED = (
    "clone_id", "parent_id", "task", "generation_index", "p0_digest",
    "admitted", "rejection_class", "gate_failed", "candidate_digest",
    "ast_distance_parent", "ast_distance_p0", "seed", "run_index",
    "fitness", "manifest_pre", "manifest_post", "attested",
    "image_digest", "python_version",
)


def _canon(rec: dict) -> bytes:
    return json.dumps(
        {k: rec.get(k) for k in CHAINED},
        sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=True,
    ).encode()


class Ledger:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA_PATH.read_text())

    def _tip(self) -> str:
        row = self.db.execute(
            "SELECT digest FROM records ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        return row[0] if row else GENESIS

    def append(self, rec: dict) -> str:
        rec = dict(rec)  # don't mutate the caller's dict
        prev = self._tip()
        rec["prev_digest"] = prev
        rec["ts_utc"] = datetime.now(timezone.utc).isoformat()
        rec["digest"] = hashlib.sha256(prev.encode() + _canon(rec)).hexdigest()
        cols = ",".join(rec)
        self.db.execute(
            f"INSERT INTO records ({cols}) VALUES ({','.join('?' * len(rec))})",
            list(rec.values()),
        )
        return rec["digest"]

    def verify_chain(self) -> bool:
        prev = GENESIS
        cur = self.db.execute("SELECT * FROM records ORDER BY seq")
        cols = [d[0] for d in cur.description]
        for row in cur:
            rec = dict(zip(cols, row))
            if rec["prev_digest"] != prev:
                return False
            if hashlib.sha256(prev.encode() + _canon(rec)).hexdigest() != rec["digest"]:
                return False
            prev = rec["digest"]
        return True

    def lineage(self, clone_id: str) -> list[dict]:
        """Walk parent_id back to genesis for one clone."""
        out, seen = [], set()
        current = clone_id
        while current is not None and current not in seen:
            seen.add(current)
            cur = self.db.execute(
                "SELECT * FROM records WHERE clone_id = ?", (current,)
            )
            cols = [d[0] for d in cur.description]
            row = cur.fetchone()
            if row is None:
                break
            rec = dict(zip(cols, row))
            out.append(rec)
            current = rec["parent_id"]
        return list(reversed(out))

    def generation(self, task: str, gen: int) -> list[dict]:
        cur = self.db.execute(
            "SELECT * FROM records WHERE task = ? AND generation_index = ?",
            (task, gen),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def close(self):
        self.db.close()
