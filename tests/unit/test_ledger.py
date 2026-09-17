import sqlite3

import pytest

from delta.ledger.chain import GENESIS, Ledger


def _rec(**overrides) -> dict:
    base = {
        "clone_id": "c0",
        "parent_id": None,
        "task": "circle_packing",
        "generation_index": 0,
        "p0_digest": "p0hash",
        "admitted": 1,
        "rejection_class": None,
        "gate_failed": None,
        "candidate_digest": "d0",
        "semantic_fingerprint": "fp0",
        "ast_distance_parent": 0.0,
        "ast_distance_p0": 0.0,
        "token_diff_parent": 0,
        "nodes_added": 0,
        "nodes_removed": 0,
        "max_depth_delta": 0,
        "seed": 1,
        "run_index": 0,
        "status": "ok",
        "fitness": 0.5,
        "manifest_pre": "mpre",
        "manifest_post": "mpre",
        "attested": 1,
        "image_digest": "python:3.12-slim",
        "python_version": "3.12.4",
        "ablation_config": None,
        "stderr_tail": None,
    }
    base.update(overrides)
    return base


def test_genesis_prev_digest(tmp_path):
    ledger = Ledger(str(tmp_path / "ledger.db"))
    ledger.append(_rec())
    row = ledger.db.execute("SELECT prev_digest FROM records WHERE seq = 1").fetchone()
    assert row[0] == GENESIS


def test_chain_links_and_verifies(tmp_path):
    ledger = Ledger(str(tmp_path / "ledger.db"))
    for i in range(5):
        ledger.append(_rec(clone_id=f"c{i}", parent_id=f"c{i-1}" if i else None,
                            generation_index=i))
    assert ledger.verify_chain() is True


def test_tamper_breaks_verification(tmp_path):
    ledger = Ledger(str(tmp_path / "ledger.db"))
    for i in range(3):
        ledger.append(_rec(clone_id=f"c{i}", generation_index=i))
    assert ledger.verify_chain() is True

    # Simulate a post-hoc edit of a chained field (ADV E01-style attack:
    # attempt to modify the ledger DB directly).
    ledger.db.execute("UPDATE records SET fitness = 999.0 WHERE clone_id = 'c1'")
    assert ledger.verify_chain() is False


def test_duplicate_clone_id_rejected(tmp_path):
    ledger = Ledger(str(tmp_path / "ledger.db"))
    ledger.append(_rec(clone_id="dup"))
    with pytest.raises(sqlite3.IntegrityError):
        ledger.append(_rec(clone_id="dup"))


def test_lineage_walks_to_genesis(tmp_path):
    ledger = Ledger(str(tmp_path / "ledger.db"))
    ledger.append(_rec(clone_id="root", parent_id=None, generation_index=0))
    ledger.append(_rec(clone_id="mid", parent_id="root", generation_index=1))
    ledger.append(_rec(clone_id="leaf", parent_id="mid", generation_index=2))

    lineage = ledger.lineage("leaf")
    assert [r["clone_id"] for r in lineage] == ["root", "mid", "leaf"]


def test_generation_query(tmp_path):
    ledger = Ledger(str(tmp_path / "ledger.db"))
    ledger.append(_rec(clone_id="a", task="circle_packing", generation_index=3))
    ledger.append(_rec(clone_id="b", task="circle_packing", generation_index=3))
    ledger.append(_rec(clone_id="c", task="circle_packing", generation_index=4))
    ledger.append(_rec(clone_id="d", task="binpacking", generation_index=3))

    gen3 = ledger.generation("circle_packing", 3)
    assert {r["clone_id"] for r in gen3} == {"a", "b"}


def test_attested_zero_recorded_for_integrity_violation(tmp_path):
    """Mirrors what evaluate.py does when manifest_pre != manifest_post."""
    ledger = Ledger(str(tmp_path / "ledger.db"))
    ledger.append(_rec(clone_id="bad", manifest_pre="A", manifest_post="B", attested=0))
    row = ledger.db.execute(
        "SELECT attested FROM records WHERE clone_id = 'bad'"
    ).fetchone()
    assert row[0] == 0
    assert ledger.verify_chain() is True  # chain integrity != candidate attestation
