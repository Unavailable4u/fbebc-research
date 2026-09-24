import importlib.util
import sys
from pathlib import Path

from delta.admission.metrics import semantic_fingerprint
from delta.admission.tasks import get_task

REPO_ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("replay_selection", REPO_ROOT / "scripts" / "replay_selection.py")
rs = importlib.util.module_from_spec(spec)
sys.modules["replay_selection"] = rs
spec.loader.exec_module(rs)

SEED = get_task("circle_packing").seed_path.read_text()
BASE = "r = 1.0 / (2 * side)"


def row(clone, gen, fit, src, *, admitted=1, attested=1):
    return {"clone_id": clone, "generation_index": gen, "admitted": admitted, "attested": attested,
            "fitness": fit, "semantic_fingerprint": semantic_fingerprint(src), "ablation_config": "single_winner_k1"}


def test_band_size_parse():
    assert rs.band_size_from_label("elite_band_k3") == 3 and rs.band_size_from_label("single_winner_k1") == 1
    assert rs.band_size_from_label(None) == 1


def test_no_divergence_when_no_constant_only_children():
    srcs = {"p0": SEED, "a": SEED.replace(BASE, "r = 0.5 / side")}      # structurally different child
    rows = [row("p0", -1, 2.0, SEED), row("a", 0, 2.5, srcs["a"])]
    res = rs.replay(rows, srcs.get, k=1)
    assert res["blocked"] == [] and res["old_best"] == res["new_best"] == 2.5


def test_constant_only_improvement_is_flagged_as_wrongly_blocked():
    srcs = {"p0": SEED, "a": SEED.replace(BASE, "r = 1.05 / (2 * side)")}   # same node types, better fitness
    rows = [row("p0", -1, 2.0, SEED), row("a", 0, 2.5, srcs["a"])]
    res = rs.replay(rows, srcs.get, k=1)
    assert res["old_best"] == 2.0 and res["new_best"] == 2.5          # old rule lost the improvement
    assert res["first_divergence"] == 0 and res["blocked"][0]["strict_improvement"] is True
    assert abs(res["blocked"][0]["gain"] - 0.5) < 1e-12


def test_invalid_unattested_and_rejected_rows_are_ignored():
    srcs = {"p0": SEED, "x": SEED.replace(BASE, "r = 1.05 / (2 * side)")}
    rows = [row("p0", -1, 2.0, SEED),
            row("x", 0, 0.0, srcs["x"]),                       # invalid packing (fitness 0)
            row("x", 1, 9.0, srcs["x"], attested=0),           # unattested
            row("x", 2, 9.0, srcs["x"], admitted=0)]           # gate rejection
    res = rs.replay(rows, srcs.get, k=3)
    assert res["blocked"] == [] and res["considered"] == 0 and res["new_best"] == 2.0


def test_missing_source_is_counted_and_never_treated_as_a_duplicate_key():
    rows = [row("p0", -1, 2.0, SEED), row("gone", 0, 2.5, SEED.replace(BASE, "r = 0.5 / side"))]
    res = rs.replay(rows, {"p0": SEED}.get, k=1)
    assert res["missing_sources"] == 1
