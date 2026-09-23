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
