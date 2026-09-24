# Week 3 Day 16: tests for the loop's new selection / baseline / retry
# behavior. Fakes only -- no Docker, no network. The single most important
# test here is the last band one: interrupt-and-resume must reproduce an
# uninterrupted run EXACTLY, including which parents were sampled.

from pathlib import Path

import pytest

from delta import checkpoint as checkpoint_mod
from delta.admission.errors import AdmissionError
from delta.admission.tasks import get_task
from delta.control.channel import ControlChannel
from delta.ledger.chain import Ledger
from delta.loop import run_generations

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_ROOTS = [REPO_ROOT / "delta", REPO_ROOT / "harness"]
TASK = get_task("circle_packing")


class NoProposal(RuntimeError):
    """Stands in for sigma.client.SigmaProposalError (no sigma import from delta tests)."""


class BudgetLike(RuntimeError):
    pass


class RecordingSigma:
    """Diffs are popped in call order; every call's parent_src is recorded.
    `script` may contain exception CLASSES/instances to raise at that call."""

    def __init__(self, script):
        self._script = list(script)
        self.calls = 0
        self.parents = []

    def propose_diff(self, *, task, parent_src, prior_rejection=None):
        self.calls += 1
        self.parents.append(parent_src)
        item = self._script.pop(0) if self._script else f"auto{self.calls}"
        if isinstance(item, BaseException) or (isinstance(item, type) and issubclass(item, BaseException)):
            raise item if isinstance(item, BaseException) else item("scripted")
        return item


def fake_admit(*, parent_src, diff_text, task, p0_src, expected_manifest, manifest_roots):
    # The diff text doubles as the semantic fingerprint, so a test controls
    # duplicates simply by reusing a diff string.
    return {
        "admitted": True, "child_src": parent_src + f"\n# {diff_text}",
        "metrics": {"semantic_fingerprint": diff_text, "exact_fingerprint": "x1:" + diff_text}, "soft_hits": [],
    }


def make_evaluate(fitness_by_gen, *, valid=True, attested=True):
    def _evaluate(*, candidate_src, task_name, seed, run_index, clone_id, parent_id,
                  generation_index, p0_digest, admission_metrics, manifest_expected,
                  manifest_roots, work_root, ledger, ablation_config=None):
        fitness = fitness_by_gen.get(generation_index, 0.0)
        ledger.append({
            "clone_id": clone_id, "parent_id": parent_id, "task": task_name,
            "generation_index": generation_index, "p0_digest": p0_digest, "admitted": 1,
            "rejection_class": None, "gate_failed": None, "candidate_digest": None,
            "semantic_fingerprint": admission_metrics.get("semantic_fingerprint"),
            "ast_distance_parent": None, "ast_distance_p0": None, "token_diff_parent": None,
            "nodes_added": None, "nodes_removed": None, "max_depth_delta": None,
            "seed": seed, "run_index": run_index, "status": "ok", "fitness": fitness,
            "manifest_pre": "m", "manifest_post": "m", "attested": int(attested),
            "image_digest": None, "python_version": None, "ablation_config": ablation_config,
            "stderr_tail": None,
        })
        return {"fitness": fitness, "valid": valid, "status": "ok", "attested": attested}
    return _evaluate


@pytest.fixture
def ledger(tmp_path):
    return Ledger(str(tmp_path / "ledger.db"))


@pytest.fixture
def work_root(tmp_path):
    d = tmp_path / "work"
    d.mkdir()
    return d


def run(ledger, work_root, sigma, fitness, n, **kw):
    kw.setdefault("admit_fn", fake_admit)
    kw.setdefault("evaluate_fn", make_evaluate(fitness))
    return run_generations(
        task=TASK, n_generations=n, ledger=ledger, work_root=work_root,
        manifest_roots=MANIFEST_ROOTS, sigma=sigma, control=ControlChannel(), **kw,
    )


# --- P_0 baseline -----------------------------------------------------------

def test_baseline_is_scored_at_generation_minus_one_and_seeds_selection(ledger, work_root):
    fit = {-1: 2.0, 0: 1.0, 1: 3.0}
    s = run(ledger, work_root, RecordingSigma(["d0", "d1"]), fit, 2, evaluate_baseline=True)
    assert s.baseline_fitness == 2.0
    # gen 0's child scored BELOW P_0: without a baseline it would have been
    # adopted (best_fitness None). With one it is kept.
    assert [g.outcome for g in s.generations] == ["kept", "improved"]
    assert s.best_fitness == 3.0
    rows = ledger.generation(TASK.name, -1)
    assert len(rows) == 1 and rows[0]["fitness"] == 2.0 and rows[0]["parent_id"] is None


def test_without_baseline_flag_behavior_is_unchanged(ledger, work_root):
    s = run(ledger, work_root, RecordingSigma(["d0"]), {0: 1.0}, 1)
    assert s.baseline_fitness is None
    assert ledger.generation(TASK.name, -1) == []
    assert [g.outcome for g in s.generations] == ["improved"]


def test_baseline_that_does_not_score_aborts_loudly(ledger, work_root):
    with pytest.raises(RuntimeError, match="P_0 baseline"):
        run(ledger, work_root, RecordingSigma(["d0"]), {-1: 0.0}, 1,
            evaluate_baseline=True, evaluate_fn=make_evaluate({}, valid=False))


def test_baseline_is_not_repeated_when_resuming(ledger, work_root, tmp_path):
    ckpt = tmp_path / "c.json"
    fit = {-1: 2.0, 0: 3.0, 1: 4.0}
    run(ledger, work_root, RecordingSigma(["d0"]), fit, 1, evaluate_baseline=True, checkpoint_path=ckpt)
    c = checkpoint_mod.load(ckpt)
    run(ledger, work_root, RecordingSigma(["d1"]), fit, 1, evaluate_baseline=True, checkpoint_path=ckpt,
        start_generation_index=c.next_generation_index, initial_parent_src=c.parent_src,
        initial_parent_id=c.parent_id, initial_best_fitness=c.best_fitness,
        initial_band=c.band)
    assert len(ledger.generation(TASK.name, -1)) == 1


# --- band selection ---------------------------------------------------------

def test_band_admits_multiple_candidates_and_evicts_worst(ledger, work_root, tmp_path):
    ckpt = tmp_path / "c.json"
    fit = {-1: 2.0, 0: 1.0, 1: 1.5, 2: 0.5, 3: 2.5}
    s = run(ledger, work_root, RecordingSigma(["d0", "d1", "d2", "d3"]), fit, 4,
            band_size=3, evaluate_baseline=True, checkpoint_path=ckpt)
    assert [g.outcome for g in s.generations] == ["improved", "improved", "kept", "improved"]
    assert s.best_fitness == 2.5
    band = checkpoint_mod.load(ckpt).band
    assert sorted(e["fitness"] for e in band) == [1.5, 2.0, 2.5]  # 1.0 evicted by 2.5


def test_band_samples_parents_beyond_the_single_best(ledger, work_root):
    fit = {-1: 1.0, **{g: 1.0 + g for g in range(1, 13)}}
    sigma = RecordingSigma([f"d{g}" for g in range(12)])
    run(ledger, work_root, sigma, {**fit, 0: 1.5}, 12, band_size=3, evaluate_baseline=True)
    assert len(set(sigma.parents)) >= 3  # a single-winner run would use one parent per improvement


def test_single_winner_uses_exactly_one_parent_at_a_time(ledger, work_root):
    fit = {-1: 1.0, 0: 0.5, 1: 0.6, 2: 0.7}  # all worse than P_0 -> parent never changes
    sigma = RecordingSigma(["d0", "d1", "d2"])
    run(ledger, work_root, sigma, fit, 3, band_size=1, evaluate_baseline=True)
    assert len(set(sigma.parents)) == 1


def test_semantic_duplicate_child_is_kept_not_admitted_to_band(ledger, work_root):
    fit = {-1: 1.0, 0: 2.0, 1: 5.0}
    s = run(ledger, work_root, RecordingSigma(["same", "same"]), fit, 2,
            band_size=3, evaluate_baseline=True)
    assert [g.outcome for g in s.generations] == ["improved", "kept"]
    assert s.best_fitness == 2.0


def test_every_ledger_row_is_tagged_with_the_selection_arm(ledger, work_root):
    run(ledger, work_root, RecordingSigma(["d0"]), {-1: 1.0, 0: 2.0}, 1,
        band_size=3, evaluate_baseline=True)
    assert {r["ablation_config"] for r in ledger.generation(TASK.name, -1) + ledger.generation(TASK.name, 0)} \
        == {"elite_band_k3"}


def test_rejection_rows_carry_the_arm_tag_too(ledger, work_root):
    def reject(*, parent_src, diff_text, task, p0_src, expected_manifest, manifest_roots):
        raise AdmissionError("E_MALFORMED_DIFF", "nope")
    run(ledger, work_root, RecordingSigma(["a", "b", "c"]), {}, 1, admit_fn=reject, band_size=1)
    rows = ledger.generation(TASK.name, 0)
    assert len(rows) == 3 and {r["ablation_config"] for r in rows} == {"single_winner_k1"}


# --- the important one: exact resume equivalence for a band ------------------

def test_band_resume_reproduces_uninterrupted_run_exactly(ledger, work_root, tmp_path):
    fit = {-1: 1.0, 0: 1.4, 1: 0.9, 2: 1.8, 3: 1.2, 4: 2.2, 5: 1.6, 6: 2.5, 7: 2.0}
    diffs = [f"d{g}" for g in range(8)]

    straight_sigma = RecordingSigma(diffs)
    straight_ckpt = tmp_path / "straight.json"
    run(Ledger(str(tmp_path / "a.db")), work_root, straight_sigma, fit, 8, band_size=3,
        evaluate_baseline=True, checkpoint_path=straight_ckpt)

    resumed_ckpt = tmp_path / "resumed.json"
    rl = Ledger(str(tmp_path / "b.db"))
    leg1 = RecordingSigma(diffs[:4])
    run(rl, work_root, leg1, fit, 4, band_size=3, evaluate_baseline=True, checkpoint_path=resumed_ckpt)
    c = checkpoint_mod.load(resumed_ckpt)
    leg2 = RecordingSigma(diffs[4:])
    run(rl, work_root, leg2, fit, 4, band_size=3, evaluate_baseline=True, checkpoint_path=resumed_ckpt,
        start_generation_index=c.next_generation_index, initial_parent_src=c.parent_src,
        initial_parent_id=c.parent_id, initial_best_fitness=c.best_fitness, initial_band=c.band)

    assert leg1.parents + leg2.parents == straight_sigma.parents  # same parent sampled every generation
    a, b = checkpoint_mod.load(straight_ckpt), checkpoint_mod.load(resumed_ckpt)
    strip = lambda band: [(e["src"], e["fitness"], e["fingerprint"]) for e in band]  # clone_ids are random uuids
    assert strip(a.band) == strip(b.band)
    assert a.next_generation_index == b.next_generation_index == 8
    assert a.best_fitness == b.best_fitness == 2.5


def test_legacy_checkpoint_without_band_still_resumes(ledger, work_root):
    # Old-format resume: only the parent_* triple is passed, no initial_band.
    s = run(ledger, work_root, RecordingSigma(["d0"]), {5: 3.0}, 1,
            start_generation_index=5, initial_parent_src="# legacy parent", initial_parent_id="legacy-1",
            initial_best_fitness=2.0)
    assert [g.outcome for g in s.generations] == ["improved"]
    assert s.best_fitness == 3.0 and s.generations[0].generation_index == 5


# --- retryable Sigma failures ----------------------------------------------

def test_unusable_sigma_reply_is_logged_and_retried_not_fatal(ledger, work_root):
    sigma = RecordingSigma([NoProposal("no hunk"), "good"])
    s = run(ledger, work_root, sigma, {0: 1.0}, 1, retry_exceptions=(NoProposal,))
    assert sigma.calls == 2
    assert [g.outcome for g in s.generations] == ["improved"]
    rej = [r for r in ledger.generation(TASK.name, 0) if r["admitted"] == 0]
    assert len(rej) == 1 and rej[0]["rejection_class"] == "E_NO_PROPOSAL"


def test_repeated_unusable_replies_stall_the_generation(ledger, work_root):
    sigma = RecordingSigma([NoProposal("x")] * 3)
    s = run(ledger, work_root, sigma, {}, 1, retry_exceptions=(NoProposal,), max_retries_per_generation=3)
    assert s.generations[0].outcome == "stalled"


def test_exceptions_not_listed_as_retryable_still_propagate(ledger, work_root):
    with pytest.raises(RuntimeError, match="auth"):
        run(ledger, work_root, RecordingSigma([RuntimeError("auth failed")]), {}, 1,
            retry_exceptions=(NoProposal,))


def test_budget_stop_still_works_alongside_retry_exceptions(ledger, work_root, tmp_path):
    ckpt = tmp_path / "c.json"
    s = run(ledger, work_root, RecordingSigma(["d0", BudgetLike("cap")]), {0: 1.0}, 3,
            stop_exceptions=(BudgetLike,), retry_exceptions=(NoProposal,), checkpoint_path=ckpt)
    assert s.stopped_reason == "BudgetLike"
    assert checkpoint_mod.load(ckpt).next_generation_index == 1
