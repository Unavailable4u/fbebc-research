import json
import time

from sigma.budget import BudgetExceeded, DailyBudget


def test_first_calls_succeed_under_cap(tmp_path):
    b = DailyBudget(tmp_path / "budget.json", daily_cap=3)
    b.check_and_reserve()
    b.check_and_reserve()
    b.check_and_reserve()
    assert b.remaining() == 0


def test_exceeding_cap_raises(tmp_path):
    b = DailyBudget(tmp_path / "budget.json", daily_cap=1)
    b.check_and_reserve()
    try:
        b.check_and_reserve()
        assert False, "expected BudgetExceeded"
    except BudgetExceeded:
        pass


def test_state_persists_across_instances(tmp_path):
    path = tmp_path / "budget.json"
    DailyBudget(path, daily_cap=5).check_and_reserve()
    DailyBudget(path, daily_cap=5).check_and_reserve()
    assert DailyBudget(path, daily_cap=5).remaining() == 3


def test_resets_on_new_utc_day(tmp_path):
    path = tmp_path / "budget.json"
    path.write_text(json.dumps({"date": "2020-01-01", "count": 999}))
    b = DailyBudget(path, daily_cap=5)
    assert b.remaining() == 5  # stale date -> treated as a fresh day
    b.check_and_reserve()  # should not raise even though old count was 999
    assert b.remaining() == 4


def test_missing_file_starts_at_zero(tmp_path):
    b = DailyBudget(tmp_path / "does_not_exist.json", daily_cap=2)
    assert b.remaining() == 2


def test_corrupt_file_treated_as_fresh(tmp_path):
    path = tmp_path / "budget.json"
    path.write_text("not json{{{")
    b = DailyBudget(path, daily_cap=2)
    assert b.remaining() == 2


# --- Week 3 Day 16: token tracking ------------------------------------------

def test_tokens_accumulate_and_persist(tmp_path):
    path = tmp_path / "b.json"
    b = DailyBudget(path, daily_cap=10)
    b.record_tokens(1200)
    b.record_tokens(800)
    assert DailyBudget(path, daily_cap=10).tokens_used() == 2000


def test_token_cap_blocks_next_call_once_reached(tmp_path):
    b = DailyBudget(tmp_path / "b.json", daily_cap=100, daily_token_cap=1000)
    b.check_and_reserve()
    b.record_tokens(1000)
    try:
        b.check_and_reserve()
        assert False, "expected BudgetExceeded"
    except BudgetExceeded as e:
        assert "token" in str(e)


def test_no_token_cap_by_default(tmp_path):
    b = DailyBudget(tmp_path / "b.json", daily_cap=100)
    b.record_tokens(10**9)
    b.check_and_reserve()  # must not raise


def test_state_file_from_before_token_tracking_still_loads(tmp_path):
    path = tmp_path / "b.json"
    path.write_text(json.dumps({"date": time.strftime("%Y-%m-%d", time.gmtime()), "count": 4}))
    b = DailyBudget(path, daily_cap=10, daily_token_cap=500)
    assert b.tokens_used() == 0 and b.remaining() == 6


def test_tokens_reset_on_new_utc_day(tmp_path):
    path = tmp_path / "b.json"
    path.write_text(json.dumps({"date": "2020-01-01", "count": 1, "tokens": 999999}))
    assert DailyBudget(path, daily_cap=5, daily_token_cap=10).tokens_used() == 0
