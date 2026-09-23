# Week 3 Day 16-20: a real circle_packing run needs multiple daily
# invocations (sigma/budget.py's cap is well under the ~1,000-call budget
# a full run needs -- see WEEK3_SETUP.md). These tests cover the two new
# behaviors that make that possible: (1) a caller-supplied exception type
# stops the loop cleanly instead of crashing, with an accurate checkpoint
# written; (2) starting a fresh run_generations() call with that
# checkpoint's state produces exactly the same outcome as if the original
# call had never been interrupted.

from pathlib import Path

import pytest

from delta import checkpoint as checkpoint_mod
from delta.admission.tasks import get_task
from delta.control.channel import ControlChannel
from delta.ledger.chain import Ledger
from delta.loop import run_generations

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_ROOTS = [REPO_ROOT / "delta", REPO_ROOT / "harness"]
TASK = get_task("circle_packing")


class BudgetLikeError(RuntimeError):
    """Stands in for sigma.budget.BudgetExceeded without importing sigma
    from a delta test -- keeps the same Sigma-Delta separation the loop
    itself preserves (see loop.py's stop_exceptions docstring)."""


class ScriptedSigma:
    def __init__(self, diffs: list[str], fail_on_call: int | None = None):
        self._diffs = list(diffs)
        self.calls = 0
        self._fail_on_call = fail_on_call

    def propose_diff(self, *, task, parent_src, prior_rejection=None):
        self.calls += 1
        if self._fail_on_call is not None and self.calls == self._fail_on_call:
            raise BudgetLikeError("daily cap reached")
        return self._diffs.pop(0) if self._diffs else "<<<<<<< SEARCH\nx\n=======\ny\n>>>>>>> REPLACE"


def _fake_admit_always_ok(*, parent_src, diff_text, task, p0_src, expected_manifest, manifest_roots):
    return {"admitted": True, "child_src": parent_src + f"\n# {diff_text[:8]}", "metrics": {}, "soft_hits": []}


def _make_fake_evaluate(fitness_by_gen: dict[int, float | None]):
    def _fake_evaluate(*, candidate_src, task_name, seed, run_index, clone_id, parent_id,
                        generation_index, p0_digest, admission_metrics, manifest_expected,
                        manifest_roots, work_root, ledger, ablation_config=None):
        fitness = fitness_by_gen.get(generation_index, 0.0)
        ledger.append({
            "clone_id": clone_id, "parent_id": parent_id, "task": task_name,
            "generation_index": generation_index, "p0_digest": p0_digest, "admitted": 1,
            "rejection_class": None, "gate_failed": None, "candidate_digest": None,
            "semantic_fingerprint": None, "ast_distance_parent": None, "ast_distance_p0": None,
            "token_diff_parent": None, "nodes_added": None, "nodes_removed": None,
            "max_depth_delta": None, "seed": seed, "run_index": run_index, "status": "ok",
            "fitness": fitness, "manifest_pre": "m", "manifest_post": "m", "attested": 1,
            "image_digest": None, "python_version": None, "ablation_config": ablation_config,
            "stderr_tail": None,
        })
        return {"fitness": fitness, "valid": True, "status": "ok", "attested": True}
    return _fake_evaluate


@pytest.fixture
def ledger(tmp_path):
    return Ledger(str(tmp_path / "ledger.db"))


@pytest.fixture
def work_root(tmp_path):
    d = tmp_path / "work"
    d.mkdir()
    return d


def test_stop_exception_ends_run_cleanly_with_checkpoint(ledger, work_root, tmp_path):
    ckpt_path = tmp_path / "run.checkpoint.json"
    sigma = ScriptedSigma(["d0", "d1", "d2"], fail_on_call=2)
    summary = run_generations(
        task=TASK, n_generations=5, ledger=ledger, work_root=work_root,
        manifest_roots=MANIFEST_ROOTS, sigma=sigma, control=ControlChannel(),
        admit_fn=_fake_admit_always_ok, evaluate_fn=_make_fake_evaluate({0: 1.0}),
        checkpoint_path=ckpt_path, stop_exceptions=(BudgetLikeError,),
    )
    # gen 0 completed (call 1), gen 1's propose_diff call (call 2) hit the
    # budget stop before anything else happened for gen 1.
    assert [g.outcome for g in summary.generations] == ["improved"]
    assert summary.stopped_reason == "BudgetLikeError"
    assert summary.best_fitness == 1.0

    loaded = checkpoint_mod.load(ckpt_path)
    assert loaded.next_generation_index == 1
    assert loaded.best_fitness == 1.0
    assert loaded.parent_src == summary.final_src
    # gen 1 never ran, so it must not be in the ledger at all
    assert ledger.generation(TASK.name, 1) == []


def test_resuming_from_checkpoint_matches_an_uninterrupted_run(ledger, work_root, tmp_path):
    """Run gens 0-2 straight through; separately, run gen 0, stop, resume
    for gens 1-2 from the saved checkpoint. Both must land on the same
    final parent source and best fitness."""
    fitness_by_gen = {0: 1.0, 1: 0.5, 2: 2.0}

    straight_ledger = Ledger(str(tmp_path / "straight.db"))
    straight_summary = run_generations(
        task=TASK, n_generations=3, ledger=straight_ledger, work_root=work_root,
        manifest_roots=MANIFEST_ROOTS, sigma=ScriptedSigma(["d0", "d1", "d2"]),
        control=ControlChannel(), admit_fn=_fake_admit_always_ok,
        evaluate_fn=_make_fake_evaluate(fitness_by_gen),
    )

    ckpt_path = tmp_path / "resumed.checkpoint.json"
    resumed_ledger = Ledger(str(tmp_path / "resumed.db"))
    first_call_sigma = ScriptedSigma(["d0"], fail_on_call=2)  # dies proposing gen 1
    first_leg = run_generations(
        task=TASK, n_generations=3, ledger=resumed_ledger, work_root=work_root,
        manifest_roots=MANIFEST_ROOTS, sigma=first_call_sigma, control=ControlChannel(),
        admit_fn=_fake_admit_always_ok, evaluate_fn=_make_fake_evaluate(fitness_by_gen),
        checkpoint_path=ckpt_path, stop_exceptions=(BudgetLikeError,),
    )
    assert first_leg.stopped_reason == "BudgetLikeError"

    ckpt = checkpoint_mod.load(ckpt_path)
    second_leg = run_generations(
        task=TASK, n_generations=3 - ckpt.next_generation_index, ledger=resumed_ledger,
        work_root=work_root, manifest_roots=MANIFEST_ROOTS, sigma=ScriptedSigma(["d1", "d2"]),
        control=ControlChannel(), admit_fn=_fake_admit_always_ok,
        evaluate_fn=_make_fake_evaluate(fitness_by_gen),
        start_generation_index=ckpt.next_generation_index, initial_parent_src=ckpt.parent_src,
        initial_parent_id=ckpt.parent_id, initial_best_fitness=ckpt.best_fitness,
        checkpoint_path=ckpt_path,
    )

    assert second_leg.final_src == straight_summary.final_src
    assert second_leg.best_fitness == straight_summary.best_fitness
    combined_outcomes = [g.outcome for g in first_leg.generations] + [g.outcome for g in second_leg.generations]
    assert combined_outcomes == [g.outcome for g in straight_summary.generations]
    # generation_index in the resumed ledger continues from 1, not restarting at 0
    assert [r["generation_index"] for r in resumed_ledger.generation(TASK.name, 0)] == [0]
    assert len(resumed_ledger.generation(TASK.name, 1)) == 1
    assert len(resumed_ledger.generation(TASK.name, 2)) == 1


def test_no_checkpoint_path_means_no_file_written(ledger, work_root, tmp_path):
    run_generations(
        task=TASK, n_generations=1, ledger=ledger, work_root=work_root,
        manifest_roots=MANIFEST_ROOTS, sigma=ScriptedSigma(["d0"]), control=ControlChannel(),
        admit_fn=_fake_admit_always_ok, evaluate_fn=_make_fake_evaluate({0: 1.0}),
    )
    assert list(tmp_path.glob("*.checkpoint.json")) == []
