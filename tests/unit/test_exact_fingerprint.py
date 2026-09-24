# Week 3 Day 17: the duplicate rule must not treat "same node types, different
# constants/names" as the same program. Regression for a bug found by reading the
# first real step-size data: semantic_fingerprint (node types only) made
# `r = 1.0/(2*side)` and `r = 100.0/(2*side)` "duplicates", so a constant-tuned
# child was rejected even when strictly fitter.

import functools
from pathlib import Path

from delta import checkpoint as checkpoint_mod
from delta.admission.metrics import edit_metrics, exact_fingerprint, semantic_fingerprint
from delta.admission.tasks import get_task
from delta.control.channel import ControlChannel
from delta.ledger.chain import Ledger
from delta.loop import run_generations
from tests.unit.test_loop_band import MANIFEST_ROOTS, RecordingSigma, make_evaluate

TASK = get_task("circle_packing")
SEED = TASK.seed_path.read_text()
BASE = "r = 1.0 / (2 * side)"


def variant(expr: str) -> str:
    assert BASE in SEED
    return SEED.replace(BASE, expr)


# --- the key itself -----------------------------------------------------------

def test_old_structure_hash_cannot_see_constants_or_names_but_exact_key_can():
    for changed in (variant("r = 100.0 / (2 * side)"), SEED.replace("side", "kk")):
        assert semantic_fingerprint(changed) == semantic_fingerprint(SEED)   # the blind spot
        assert exact_fingerprint(changed) != exact_fingerprint(SEED)         # the fix


def test_exact_key_still_ignores_layout_comments_and_docstrings():
    reformatted = SEED.replace(BASE, "r = 1.0/(2*side)   # a comment")
    reformatted = reformatted.replace('CONTRACT: signature fixed.', 'CONTRACT:   signature   fixed.')
    assert exact_fingerprint(reformatted) == exact_fingerprint(SEED)


def test_key_is_versioned_and_edit_metrics_carries_it():
    child = variant("r = 0.5 / side")
    m = edit_metrics(SEED, child, SEED)
    assert m["exact_fingerprint"] == exact_fingerprint(child) and m["exact_fingerprint"].startswith("x1:")
    assert m["semantic_fingerprint"] == semantic_fingerprint(child)   # frozen field unchanged


# --- through the real loop, with the real metrics ------------------------------

def _real_metrics_admit(replacements):
    """admit_fn that builds a REAL child from the parent and returns REAL edit_metrics."""
    it = iter(replacements)

    def admit(*, parent_src, diff_text, task, p0_src, expected_manifest, manifest_roots):
        child = SEED.replace(BASE, next(it))
        return {"admitted": True, "child_src": child, "metrics": edit_metrics(parent_src, child, p0_src), "soft_hits": []}
    return admit


def _run(tmp_path, exprs, fit, band_size, **kw):
    led = Ledger(str(tmp_path / f"l{band_size}.db"))
    ckpt = tmp_path / f"c{band_size}.json"
    s = run_generations(
        task=TASK, n_generations=len(exprs), ledger=led, work_root=tmp_path, manifest_roots=MANIFEST_ROOTS,
        sigma=RecordingSigma([f"d{i}" for i in range(len(exprs))]), control=ControlChannel(),
        admit_fn=_real_metrics_admit(exprs), evaluate_fn=make_evaluate(fit), band_size=band_size,
        evaluate_baseline=True, checkpoint_path=ckpt, **kw,
    )
    led.close()
    return s, checkpoint_mod.load(ckpt)


def test_constant_tuned_improvement_is_admitted_single_winner(tmp_path):
    # gen0: same node types as the seed but a different constant, and fitter.
    s, ck = _run(tmp_path, ["r = 1.02 / (2 * side)"], {-1: 2.0, 0: 2.5}, band_size=1)
    assert [g.outcome for g in s.generations] == ["improved"] and s.best_fitness == 2.5


def test_constant_tuned_improvement_is_admitted_elite_band(tmp_path):
    s, ck = _run(tmp_path, ["r = 1.02 / (2 * side)", "r = 1.03 / (2 * side)"], {-1: 2.0, 0: 2.5, 1: 2.6}, band_size=3)
    assert [g.outcome for g in s.generations] == ["improved", "improved"]
    assert s.best_fitness == 2.6 and len(ck.band) == 3


def test_layout_only_rewrite_is_still_a_duplicate(tmp_path):
    s, _ = _run(tmp_path, ["r = 1.0/(2*side)  # same program"], {-1: 2.0, 0: 9.9}, band_size=3)
    assert [g.outcome for g in s.generations] == ["kept"]   # identical program: no new band member


def test_checkpoint_written_with_the_old_key_is_rederived_on_resume(tmp_path):
    legacy = [{"src": SEED, "clone_id": "old-1", "fitness": 2.0,
               "fingerprint": semantic_fingerprint(SEED)}]   # old node-type-only key, no "x1:" prefix
    s, ck = _run(tmp_path, ["r = 1.02 / (2 * side)", "r = 1.0/(2*side)"], {5: 3.0, 6: 9.0}, band_size=3,
                 start_generation_index=5, initial_parent_src=SEED, initial_parent_id="old-1",
                 initial_best_fitness=2.0, initial_band=legacy)
    # constant-tuned child enters (old key would have called it a duplicate); the layout-only twin of the
    # seed is recognized as a duplicate via the RE-DERIVED key.
    assert [g.outcome for g in s.generations] == ["improved", "kept"]
    assert all(e["fingerprint"].startswith("x1:") for e in ck.band)
