from delta import checkpoint as checkpoint_mod


def test_save_then_load_round_trips_all_fields(tmp_path):
    path = tmp_path / "run.checkpoint.json"
    ckpt = checkpoint_mod.RunCheckpoint(
        task_name="circle_packing", seed_base=7, next_generation_index=42,
        parent_src="def candidate_packing(n): ...", parent_id="circle_packing-g41-abcd1234",
        best_fitness=3.14,
    )
    checkpoint_mod.save(path, ckpt)
    loaded = checkpoint_mod.load(path)
    assert loaded == ckpt


def test_load_missing_file_returns_none(tmp_path):
    assert checkpoint_mod.load(tmp_path / "nope.json") is None


def test_save_overwrites_previous_checkpoint_atomically(tmp_path):
    path = tmp_path / "run.checkpoint.json"
    checkpoint_mod.save(path, checkpoint_mod.RunCheckpoint(
        task_name="circle_packing", seed_base=0, next_generation_index=1,
        parent_src="a", parent_id=None, best_fitness=None,
    ))
    checkpoint_mod.save(path, checkpoint_mod.RunCheckpoint(
        task_name="circle_packing", seed_base=0, next_generation_index=2,
        parent_src="b", parent_id="clone-1", best_fitness=1.5,
    ))
    loaded = checkpoint_mod.load(path)
    assert loaded.next_generation_index == 2
    assert loaded.parent_src == "b"
    assert loaded.best_fitness == 1.5
    # no leftover .tmp file
    assert not path.with_suffix(path.suffix + ".tmp").exists()


def test_default_path_for_ledger_derives_a_sibling_json_path(tmp_path):
    ledger_path = tmp_path / "run_seed0.db"
    ckpt_path = checkpoint_mod.default_path_for_ledger(ledger_path)
    assert ckpt_path.name == "run_seed0.db.checkpoint.json"
    assert ckpt_path.parent == ledger_path.parent


# --- Week 3 Day 16: band state ------------------------------------------------

def test_band_round_trips_and_preserves_order(tmp_path):
    path = tmp_path / "run.checkpoint.json"
    band = [
        {"src": "b", "clone_id": "c2", "fitness": 2.0, "fingerprint": "fb"},
        {"src": "a", "clone_id": "c1", "fitness": 1.0, "fingerprint": "fa"},
    ]
    ckpt = checkpoint_mod.RunCheckpoint(
        task_name="circle_packing", seed_base=0, next_generation_index=9, parent_src="b",
        parent_id="c2", best_fitness=2.0, band_size=3, band=band,
    )
    checkpoint_mod.save(path, ckpt)
    assert checkpoint_mod.load(path) == ckpt


def test_checkpoint_written_before_band_support_still_loads(tmp_path):
    import json
    path = tmp_path / "old.checkpoint.json"
    path.write_text(json.dumps({
        "task_name": "binpacking", "seed_base": 0, "next_generation_index": 5,
        "parent_src": "x", "parent_id": "id", "best_fitness": -28.0,
    }))
    loaded = checkpoint_mod.load(path)
    assert loaded.band is None and loaded.band_size == 1 and loaded.best_fitness == -28.0
