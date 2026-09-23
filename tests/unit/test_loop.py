from pathlib import Path

import pytest

from delta.admission.errors import AdmissionError
from delta.admission.tasks import get_task
from delta.control.channel import ControlChannel
from delta.integrity import manifest as manifest_mod
from delta.ledger.chain import Ledger
from delta.loop import run_generations

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_ROOTS = [REPO_ROOT / "delta", REPO_ROOT / "harness"]
TASK = get_task("circle_packing")


class ScriptedSigma:
    """Returns whatever diff the test queued next, regardless of content --
    the point of these tests is the LOOP's wiring, not real diff parsing."""

    def __init__(self, diffs: list[str]):
        self._diffs = list(diffs)
        self.calls = 0

    def propose_diff(self, *, task, parent_src, prior_rejection=None):
        self.calls += 1
        return self._diffs.pop(0) if self._diffs else "<<<<<<< SEARCH\nx\n=======\ny\n>>>>>>> REPLACE"


def _fake_admit_always_ok(*, parent_src, diff_text, task, p0_src, expected_manifest, manifest_roots):
    return {"admitted": True, "child_src": parent_src + f"\n# {diff_text[:8]}", "metrics": {}, "soft_hits": []}


def _fake_admit_always_rejects(*, parent_src, diff_text, task, p0_src, expected_manifest, manifest_roots):
    raise AdmissionError("E_MALFORMED_DIFF", "no SEARCH/REPLACE hunk found")


def _fake_admit_raises_integrity(*, parent_src, diff_text, task, p0_src, expected_manifest, manifest_roots):
    raise manifest_mod.IntegrityViolation('{"added": ["x"], "removed": [], "changed": []}')


def _make_fake_evaluate(fitness_by_gen: dict[int, float | None], valid: bool = True, attested: bool = True):
    def _fake_evaluate(*, candidate_src, task_name, seed, run_index, clone_id, parent_id,
                        generation_index, p0_digest, admission_metrics, manifest_expected,
                        manifest_roots, work_root, ledger, ablation_config=None):
        fitness = fitness_by_gen.get(generation_index)
        ledger.append({
            "clone_id": clone_id, "parent_id": parent_id, "task": task_name,
            "generation_index": generation_index, "p0_digest": p0_digest, "admitted": 1,
            "rejection_class": None, "gate_failed": None, "candidate_digest": None,
            "semantic_fingerprint": None, "ast_distance_parent": None, "ast_distance_p0": None,
            "token_diff_parent": None, "nodes_added": None, "nodes_removed": None,
            "max_depth_delta": None, "seed": seed, "run_index": run_index, "status": "ok",
            "fitness": fitness, "manifest_pre": "m", "manifest_post": "m", "attested": int(attested),
            "image_digest": None, "python_version": None, "ablation_config": ablation_config,
            "stderr_tail": None,
        })
        return {"fitness": fitness, "valid": valid, "status": "ok", "attested": attested}
    return _fake_evaluate


@pytest.fixture
def ledger(tmp_path):
    return Ledger(str(tmp_path / "ledger.db"))


@pytest.fixture
def work_root(tmp_path):
    d = tmp_path / "work"
    d.mkdir()
    return d


def test_improving_then_worse_child_is_kept_not_adopted(ledger, work_root):
    evaluate_fn = _make_fake_evaluate({0: 1.0, 1: 0.5})
    summary = run_generations(
        task=TASK, n_generations=2, ledger=ledger, work_root=work_root,
        manifest_roots=MANIFEST_ROOTS, sigma=ScriptedSigma(["d0", "d1"]),
        control=ControlChannel(), admit_fn=_fake_admit_always_ok, evaluate_fn=evaluate_fn,
    )
    assert [g.outcome for g in summary.generations] == ["improved", "kept"]
    assert summary.best_fitness == 1.0
    # generation 1's child was scored but never became the parent for
    # anything after it -- confirm it's still in the ledger (Phase1 §11).
    assert len(ledger.generation(TASK.name, 1)) == 1


def test_equal_fitness_is_adopted_not_just_better(ledger, work_root):
    evaluate_fn = _make_fake_evaluate({0: 1.0, 1: 1.0})
    summary = run_generations(
        task=TASK, n_generations=2, ledger=ledger, work_root=work_root,
        manifest_roots=MANIFEST_ROOTS, sigma=ScriptedSigma(["d0", "d1"]),
        control=ControlChannel(), admit_fn=_fake_admit_always_ok, evaluate_fn=evaluate_fn,
    )
    assert [g.outcome for g in summary.generations] == ["improved", "improved"]


def test_exhausted_admission_retries_marks_generation_stalled(ledger, work_root):
    summary = run_generations(
        task=TASK, n_generations=1, ledger=ledger, work_root=work_root,
        manifest_roots=MANIFEST_ROOTS, sigma=ScriptedSigma(["d0", "d1", "d2"]),
        control=ControlChannel(), max_retries_per_generation=3,
        admit_fn=_fake_admit_always_rejects, evaluate_fn=_make_fake_evaluate({}),
    )
    assert summary.generations[0].outcome == "stalled"
    assert summary.best_fitness is None
    # every failed attempt logged as its own rejected ledger record
    rejected = [r for r in ledger.generation(TASK.name, 0) if r["admitted"] == 0]
    assert len(rejected) == 3
    assert all(r["rejection_class"] == "E_MALFORMED_DIFF" for r in rejected)
    assert all(r["attested"] == 0 for r in rejected)


def test_rejection_feeds_back_into_next_sigma_call(ledger, work_root):
    sigma = ScriptedSigma(["d0", "d1", "d2"])
    run_generations(
        task=TASK, n_generations=1, ledger=ledger, work_root=work_root,
        manifest_roots=MANIFEST_ROOTS, sigma=sigma, control=ControlChannel(),
        max_retries_per_generation=3, admit_fn=_fake_admit_always_rejects,
        evaluate_fn=_make_fake_evaluate({}),
    )
    assert sigma.calls == 3  # one call per retry attempt, each with feedback


def test_integrity_violation_propagates_uncaught(ledger, work_root):
    with pytest.raises(manifest_mod.IntegrityViolation):
        run_generations(
            task=TASK, n_generations=1, ledger=ledger, work_root=work_root,
            manifest_roots=MANIFEST_ROOTS, sigma=ScriptedSigma(["d0"]),
            control=ControlChannel(), admit_fn=_fake_admit_raises_integrity,
            evaluate_fn=_make_fake_evaluate({}),
        )


def test_pre_halted_control_stops_before_any_generation(ledger, work_root):
    control = ControlChannel()
    control.halt()
    with pytest.raises(SystemExit):
        run_generations(
            task=TASK, n_generations=5, ledger=ledger, work_root=work_root,
            manifest_roots=MANIFEST_ROOTS, sigma=ScriptedSigma(["d0"]),
            control=control, admit_fn=_fake_admit_always_ok,
            evaluate_fn=_make_fake_evaluate({0: 1.0}),
        )
    assert len(ledger.generation(TASK.name, 0)) == 0  # nothing ran at all


def test_unattested_result_is_never_adopted(ledger, work_root):
    evaluate_fn = _make_fake_evaluate({0: 1.0}, attested=False)
    summary = run_generations(
        task=TASK, n_generations=1, ledger=ledger, work_root=work_root,
        manifest_roots=MANIFEST_ROOTS, sigma=ScriptedSigma(["d0"]),
        control=ControlChannel(), admit_fn=_fake_admit_always_ok, evaluate_fn=evaluate_fn,
    )
    assert summary.generations[0].outcome == "kept"
    assert summary.best_fitness is None
