# Only the pure, no-network helper from scripts/run_stage1.py is unit
# tested here. The rest of that file constructs a real SigmaClient (needs
# GROQ_API_KEY) and a real Docker sandbox -- exercised for real on your own
# machine per WEEK3_SETUP.md, not here (same split as sigma/client.py's
# own docstring: "run python -m sigma.client first thing ... to catch
# anything that only shows up against the live API").

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_run_stage1():
    spec = importlib.util.spec_from_file_location("run_stage1", REPO_ROOT / "scripts" / "run_stage1.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["run_stage1"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_single_seed_ledger_path_is_unchanged():
    mod = _load_run_stage1()
    assert mod._ledger_path_for_seed("run_ledger.db", 0, multi=False) == "run_ledger.db"


def test_multi_seed_ledger_path_gets_seed_suffix_before_extension():
    mod = _load_run_stage1()
    assert mod._ledger_path_for_seed("run_ledger.db", 1000, multi=True) == "run_ledger.seed1000.db"


def test_multi_seed_ledger_path_respects_directory():
    mod = _load_run_stage1()
    path = str(REPO_ROOT / "runs" / "week3.db")
    expected = str(REPO_ROOT / "runs" / "week3.seed7.db")
    assert mod._ledger_path_for_seed(path, 7, multi=True) == expected


# --- Week 3 Day 16: arms, round-robin, resume, budget stops ------------------

import json  # noqa: E402
from types import SimpleNamespace  # noqa: E402

import pytest  # noqa: E402

from delta import checkpoint as checkpoint_mod  # noqa: E402
from delta.ledger.chain import Ledger  # noqa: E402
from sigma.budget import BudgetExceeded  # noqa: E402


def test_arm_ledger_path_encodes_condition_and_seed():
    mod = _load_run_stage1()
    assert mod._arm_ledger_path("runs/w3.db", "elite_band", 1000) == "runs/w3.elite_band.seed1000.db"


def test_build_arms_pairs_conditions_per_seed_and_sets_band_sizes():
    mod = _load_run_stage1()
    arms = mod.build_arms(["single_winner", "elite_band"], [0, 1000], 3, "runs/w3.db")
    assert [(a.condition, a.seed_base, a.band_size) for a in arms] == [
        ("single_winner", 0, 1), ("elite_band", 0, 3), ("single_winner", 1000, 1), ("elite_band", 1000, 3),
    ]
    assert len({a.ledger_path for a in arms}) == 4


def test_build_arms_single_condition_keeps_the_legacy_ledger_names():
    mod = _load_run_stage1()
    arms = mod.build_arms(["single_winner"], [0, 1000], 3, "runs/w3.db")
    assert [a.ledger_path for a in arms] == ["runs/w3.seed0.db", "runs/w3.seed1000.db"]


def _fake_runner(done, *, stop_after=None):
    """run_arm_fn stand-in that advances `done` and can simulate the shared
    daily budget dying after `stop_after` chunks."""
    calls = []

    def run_arm(arm, n):
        if stop_after is not None and len(calls) >= stop_after:
            return 3
        calls.append((arm.label, n))
        done[arm] += n
        return 0
    return run_arm, calls


def test_run_batch_advances_arms_round_robin_to_the_target():
    mod = _load_run_stage1()
    arms = mod.build_arms(["single_winner", "elite_band"], [0], 3, "r.db")
    done = {a: 0 for a in arms}
    run_arm, calls = _fake_runner(done)
    code = mod.run_batch(arms, target=25, round_size=10, legacy_generations=5,
                         done_fn=lambda a: done[a], run_arm_fn=run_arm)
    assert code == 0 and all(v == 25 for v in done.values())
    # strictly interleaved: never two chunks in a row for the same arm while the other lags
    assert [c[0] for c in calls][:4] == ["single_winner/seed0", "elite_band/seed0"] * 2


def test_budget_stop_halts_the_whole_batch_and_leaves_arms_matched():
    mod = _load_run_stage1()
    arms = mod.build_arms(["single_winner", "elite_band"], [0, 1000], 3, "r.db")
    done = {a: 0 for a in arms}
    run_arm, calls = _fake_runner(done, stop_after=6)  # 4 arms: 1.5 rounds done, then budget dies
    code = mod.run_batch(arms, target=100, round_size=10, legacy_generations=5,
                         done_fn=lambda a: done[a], run_arm_fn=run_arm)
    assert code == 3
    assert max(done.values()) - min(done.values()) <= 10  # matched to within one chunk


def test_rerunning_after_the_target_is_reached_does_nothing():
    mod = _load_run_stage1()
    arms = mod.build_arms(["single_winner"], [0], 1, "r.db")
    done = {a: 100 for a in arms}
    run_arm, calls = _fake_runner(done)
    assert mod.run_batch(arms, target=100, round_size=10, legacy_generations=5,
                         done_fn=lambda a: done[a], run_arm_fn=run_arm) == 0
    assert calls == []


def test_no_progress_round_is_refused_instead_of_looping_forever():
    mod = _load_run_stage1()
    arms = mod.build_arms(["single_winner"], [0], 1, "r.db")
    assert mod.run_batch(arms, target=10, round_size=5, legacy_generations=5,
                         done_fn=lambda a: 0, run_arm_fn=lambda a, n: 0) == 4


def test_legacy_mode_is_a_single_pass_of_n_more_per_arm():
    mod = _load_run_stage1()
    arms = mod.build_arms(["single_winner"], [0, 1000], 1, "r.db")
    done = {a: 0 for a in arms}
    run_arm, calls = _fake_runner(done)
    assert mod.run_batch(arms, target=None, round_size=10, legacy_generations=7,
                         done_fn=lambda a: done[a], run_arm_fn=run_arm) == 0
    assert calls == [("single_winner/seed0", 7), ("single_winner/seed1000", 7)]


def test_archive_existing_renames_instead_of_deleting(tmp_path):
    mod = _load_run_stage1()
    arm = mod.Arm("single_winner", 0, 1, str(tmp_path / "a.db"))
    (tmp_path / "a.db").write_text("ledger")
    checkpoint_mod.default_path_for_ledger(tmp_path / "a.db").write_text("{}")
    mod._archive_existing(arm)
    names = sorted(p.name for p in tmp_path.iterdir())
    assert not (tmp_path / "a.db").exists()
    assert any(n.startswith("a.db.bak-") for n in names) and any(n.startswith("a.db.checkpoint.json.bak-") for n in names)


def test_dirty_flag_only_watches_run_affecting_code():
    mod = _load_run_stage1()
    assert "delta" in mod.RUN_CODE_PATHS and "sigma" in mod.RUN_CODE_PATHS
    assert "STATUS.md" not in mod.RUN_CODE_PATHS and "DRAFT.md" not in mod.RUN_CODE_PATHS
    assert "scripts/summarize_ledgers.py" not in mod.RUN_CODE_PATHS


def test_run_meta_appends_one_record_per_invocation(tmp_path):
    mod = _load_run_stage1()
    arms = mod.build_arms(["single_winner"], [0], 1, str(tmp_path / "w3.db"))
    args = SimpleNamespace(task="circle_packing", target_generations=10)
    mod._write_run_meta(str(tmp_path / "w3.db"), args, arms, "some-model")
    mod._write_run_meta(str(tmp_path / "w3.db"), args, arms, "some-model")
    meta = json.loads((tmp_path / "w3.runmeta.json").read_text())
    assert len(meta["invocations"]) == 2 and meta["model"] == "some-model"
    assert {"git_commit", "git_dirty", "image_digest", "ts_utc", "prompt_version", "prompt_sha256"} <= set(meta["invocations"][0])
    assert meta["invocations"][0]["prompt_version"] == "v2" and len(meta["invocations"][0]["prompt_sha256"]) == 64


# --- end to end with fakes: real run_one_arm + real loop + real ledger --------

class _FakeSigma:
    def __init__(self, calls_allowed):
        self.calls, self.allowed = 0, calls_allowed
        self.budget = SimpleNamespace(daily_cap=900, remaining=lambda: 900 - self.calls, tokens_used=lambda: 0)

    def propose_diff(self, *, task, parent_src, prior_rejection=None):
        if self.calls >= self.allowed:
            raise BudgetExceeded("fake daily cap")
        self.calls += 1
        return f"diff{self.calls}"


def _patch_loop_with_fakes(mod, monkeypatch):
    import functools
    from tests.unit.test_loop_band import fake_admit, make_evaluate

    fit = {g: 1.0 + 0.05 * g for g in range(-1, 200)}
    fit[-1] = 1.0
    real = mod.run_generations
    monkeypatch.setattr(mod, "run_generations",
                        functools.partial(real, admit_fn=fake_admit, evaluate_fn=make_evaluate(fit)))


def test_multiday_matched_run_end_to_end_with_fakes(tmp_path, monkeypatch):
    mod = _load_run_stage1()
    _patch_loop_with_fakes(mod, monkeypatch)
    arms = mod.build_arms(["single_winner", "elite_band"], [0], 3, str(tmp_path / "w3.db"))

    def invoke(calls_allowed):
        sigma = _FakeSigma(calls_allowed)
        return mod.run_batch(
            arms, target=12, round_size=4, legacy_generations=5, done_fn=mod._generations_done,
            run_arm_fn=lambda arm, n: mod.run_one_arm(arm, n, task_name="circle_packing", sigma=sigma, verbose=False),
        )

    assert invoke(calls_allowed=10) == 3            # "day 1": budget dies mid-experiment
    d1 = [mod._generations_done(a) for a in arms]
    assert max(d1) - min(d1) <= 4 and 0 < min(d1)   # matched, and real progress was made
    assert invoke(calls_allowed=100) == 0           # "day 2": same command finishes it
    assert [mod._generations_done(a) for a in arms] == [12, 12]
    assert invoke(calls_allowed=100) == 0           # "day 3": nothing left to do
    for a in arms:
        led = Ledger(a.ledger_path)
        try:
            assert led.verify_chain()
            assert len(led.generation("circle_packing", -1)) == 1   # baseline scored exactly once across all resumes
            row = led.generation("circle_packing", 0)[0]
            assert row["ablation_config"] == ("single_winner_k1" if a.band_size == 1 else "elite_band_k3")
        finally:
            led.close()
    ck = checkpoint_mod.load(checkpoint_mod.default_path_for_ledger(Path(arms[1].ledger_path)))
    assert ck.band_size == 3 and len(ck.band) == 3


def test_changing_band_size_on_an_existing_arm_is_refused(tmp_path, monkeypatch):
    mod = _load_run_stage1()
    _patch_loop_with_fakes(mod, monkeypatch)
    arm3 = mod.Arm("elite_band", 0, 3, str(tmp_path / "x.db"))
    assert mod.run_one_arm(arm3, 2, task_name="circle_packing", sigma=_FakeSigma(50), verbose=False) == 0
    arm5 = mod.Arm("elite_band", 0, 5, str(tmp_path / "x.db"))
    assert mod.run_one_arm(arm5, 2, task_name="circle_packing", sigma=_FakeSigma(50), verbose=False) == 2


# --- Week 3 Day 16 (post-launch): multi-day arm drift regression ---------------

def _spread(done):
    return max(done.values()) - min(done.values())


def test_arms_stay_within_one_chunk_across_many_interrupted_days():
    """Regression for a bug found from the first real launch's arm counts
    ([13, 10, 10, 10, 10, 10] after day 1): a scheduler that gives every arm a
    chunk per round STARTING FROM THE SAME ARM each invocation lets the early
    arms gain an extra chunk every time a daily cut lands mid-round, so the
    lead ACCUMULATES across days. The property that matters for a matched
    ablation: after ANY day's stop, no arm leads another by more than one
    chunk (plus a pre-existing odd offset)."""
    mod = _load_run_stage1()
    arms = mod.build_arms(["single_winner", "elite_band"], [0, 1000, 2000], 3, "r.db")
    done = {a: 10 for a in arms}
    done[arms[0]] = 13                       # the actual post-launch state
    round_size, target, budget_chunks_per_day = 10, 100, 4   # 4 does not divide 6 arms -> cut lands mid-round daily
    for day in range(1, 60):
        run_arm, _ = _fake_runner(done, stop_after=budget_chunks_per_day)
        code = mod.run_batch(arms, target=target, round_size=round_size, legacy_generations=5,
                             done_fn=lambda a: done[a], run_arm_fn=run_arm)
        if code == 0:
            break
        assert _spread(done) <= round_size + 3, f"day {day}: arms drifted apart: {sorted(done.values())}"
    assert code == 0 and all(v == target for v in done.values())


def test_next_chunk_always_advances_the_least_progressed_arm():
    mod = _load_run_stage1()
    a, b, c = (mod.Arm("single_winner", s, 1, f"x{s}.db") for s in (0, 1, 2))
    assert mod.next_chunk([a, b, c], {a: 13, b: 10, c: 10}, target=100, round_size=10) == (b, 10)   # tie -> listed order
    assert mod.next_chunk([a, b, c], {a: 13, b: 20, c: 10}, target=100, round_size=10) == (c, 10)
    assert mod.next_chunk([a, b, c], {a: 100, b: 96, c: 100}, target=100, round_size=10) == (b, 4)   # clamped at target
    assert mod.next_chunk([a, b, c], {a: 100, b: 100, c: 100}, target=100, round_size=10) is None
