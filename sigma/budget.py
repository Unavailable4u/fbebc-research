# sigma/budget.py
#
# Groq's free tier does not queue or soft-fail a request that would exceed
# the daily cap -- per Groq's own docs, exceeding any limit (RPM/TPM/RPD/TPD)
# returns an immediate 429. Refusing client-side, before spending a network
# round trip, gets you the same outcome with a clearer local error and one
# fewer wasted request against an already-scarce daily allowance.
#
# This tracks REQUEST count only, not tokens -- a deliberately conservative
# simplification: request count is the cheaper thing to reason about
# up front, and openai/gpt-oss-120b's free-tier daily REQUEST cap
# (around 1,000/day, per Groq's real rate-limit responses -- verify current
# numbers on your own account's limits page, these move) is comfortably
# the binding constraint for this pipeline's small per-request token counts.

import json
import time
from pathlib import Path


class BudgetExceeded(RuntimeError):
    pass


def _today_utc() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


class DailyBudget:
    def __init__(self, path: Path, daily_cap: int):
        self.path = Path(path)
        self.daily_cap = daily_cap

    def _load(self) -> dict:
        try:
            state = json.loads(self.path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return {"date": _today_utc(), "count": 0}
        if state.get("date") != _today_utc():
            return {"date": _today_utc(), "count": 0}
        return state

    def _save(self, state: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(state))

    def check_and_reserve(self) -> None:
        """Call once immediately before firing a request. Raises
        BudgetExceeded instead of letting the request go out and 429."""
        state = self._load()
        if state["count"] >= self.daily_cap:
            raise BudgetExceeded(
                f"local daily request budget ({self.daily_cap}) reached for "
                f"{state['date']} UTC. Wait for UTC midnight reset, or pass "
                f"a higher daily_request_cap if your account's real limit "
                f"is higher than this conservative default."
            )
        state["count"] += 1
        self._save(state)

    def remaining(self) -> int:
        state = self._load()
        return max(0, self.daily_cap - state["count"])
