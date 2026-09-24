# Tests for scripts/usage_report.py and scripts/summarize_ledgers.py -- the
# two scripts whose printed output drives the Week 3 decisions, so their
# arithmetic is pinned here rather than trusted by eye.

import functools
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

from delta.admission.tasks import get_task
from delta.control.channel import ControlChannel
from delta.ledger.chain import Ledger
from delta.loop import run_generations
from tests.unit.test_loop_band import MANIFEST_ROOTS, RecordingSigma, fake_admit, make_evaluate

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# --- usage_report ------------------------------------------------------------

def test_project_token_limited_case_matches_hand_arithmetic():
    ur = _load("usage_report")
    p = ur.project(tokens_per_call=1500, tpd=200_000, rpd=1000, calls_per_gen=1.6, days=8, arms=6)
    assert p["binding_limit"] == "tokens/day"
    assert round(p["calls_per_day"]) == 133            # 200000 / 1500
    assert round(p["gens_per_day"]) == 83               # 133.3 / 1.6
    assert round(p["gens_per_arm"]) == 111              # 83.3 * 8 / 6


def test_project_request_limited_case():
    ur = _load("usage_report")
    p = ur.project(tokens_per_call=100, tpd=200_000, rpd=1000, calls_per_gen=2.0, days=1, arms=1)
    assert p["binding_limit"] == "requests/day" and p["calls_per_day"] == 1000 and p["gens_per_day"] == 500


def test_summarize_and_load_rows_skip_corrupt_lines(tmp_path):
    ur = _load("usage_report")
    log = tmp_path / "u.jsonl"
    rows = [{"ts_utc": "2026-09-25T01:00:00Z", "prompt_tokens": 900, "completion_tokens": t - 900,
             "total_tokens": t, "reasoning_tokens": 100, "finish_reason": "stop"} for t in (1000, 2000, 3000)]
    log.write_text("\n".join(json.dumps(r) for r in rows) + "\nnot json\n")
    loaded = ur.load_rows(log)
    assert len(loaded) == 3
    s = ur.summarize(loaded)
    assert s["mean_total"] == 2000 and s["median_total"] == 2000 and s["max_total"] == 3000
    assert ur.load_rows(log, since_date="2026-09-26") == []


# --- summarize_ledgers -------------------------------------------------------

def _make_arm(tmp_path, name, fit, *, band_size, n, diffs=None):
    led = Ledger(str(tmp_path / name))
    run_generations(
        task=get_task("circle_packing"), n_generations=n, ledger=led, work_root=tmp_path,
        manifest_roots=MANIFEST_ROOTS, sigma=RecordingSigma(diffs or [f"d{g}" for g in range(n)]),
        control=ControlChannel(), admit_fn=fake_admit, evaluate_fn=make_evaluate(fit),
        band_size=band_size, evaluate_baseline=True, seed_base=1000,
    )
    led.close()
    return str(tmp_path / name)


def test_analyze_reports_baseline_best_curve_and_seed(tmp_path):
    sl = _load("summarize_ledgers")
    fit = {-1: 2.0, 0: 1.0, 1: 2.5, 2: 2.2, 3: 3.0}
    path = _make_arm(tmp_path, "a.db", fit, band_size=1, n=4)
    a = sl.analyze(sl.read_rows(path))
    assert a["baseline"] == 2.0 and a["best"] == 3.0 and a["n_generations"] == 4
    assert a["label"] == "single_winner_k1" and a["seed_base"] == 1000
    assert [sl.best_at(a, n) for n in (0, 1, 2, 4)] == [2.0, 2.0, 2.5, 3.0]
    assert a["calls_per_gen"] == 1.0
    assert a["n_baseline_rows"] == 1


def test_analyze_counts_rejections_and_invalid_packings(tmp_path):
    sl = _load("summarize_ledgers")
    fit = {-1: 2.0, 0: 0.0, 1: 2.5}  # gen 0's candidate ran but scored 0.0 == invalid packing
    path = _make_arm(tmp_path, "b.db", fit, band_size=1, n=2)
    a = sl.analyze(sl.read_rows(path))
    assert a["invalid_packings"] == 1
    assert a["status"] == {"ok": 2}


def test_chain_verification_detects_tampering(tmp_path):
    sl = _load("summarize_ledgers")
    path = _make_arm(tmp_path, "c.db", {-1: 2.0, 0: 3.0}, band_size=1, n=1)
    assert sl.verify_chain_rows(sl.read_rows(path)) is True
    con = sqlite3.connect(path)
    con.execute("UPDATE records SET fitness = 99.0 WHERE generation_index = 0")
    con.commit(); con.close()
    assert sl.verify_chain_rows(sl.read_rows(path)) is False


def test_read_only_open_never_creates_or_modifies_a_ledger(tmp_path):
    sl = _load("summarize_ledgers")
    missing = tmp_path / "typo.db"
    with pytest.raises(sqlite3.Error):
        sl.read_rows(str(missing))
    assert not missing.exists()


def test_comparison_uses_the_matched_generation_count(tmp_path, capsys):
    sl = _load("summarize_ledgers")
    fit = {-1: 1.0, **{g: 1.0 + 0.1 * g for g in range(0, 10)}}
    p1 = _make_arm(tmp_path, "single.db", fit, band_size=1, n=8)
    p2 = _make_arm(tmp_path, "band.db", fit, band_size=3, n=6)   # one arm is behind
    arms = {p: sl.analyze(sl.read_rows(p)) for p in (p1, p2)}
    sl.print_comparison(arms)
    out = capsys.readouterr().out
    assert "@ 6 generations" in out and "single_winner_k1" in out and "elite_band_k3" in out
