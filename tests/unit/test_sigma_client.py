import io
import json
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from delta.admission.tasks import get_task
from sigma.budget import BudgetExceeded
from sigma.client import SigmaClient, SigmaError
from sigma.prompts import build_messages

TASK = get_task("circle_packing")
GOOD_DIFF = "<<<<<<< SEARCH\nr = 1.0 / (2 * side)\n=======\nr = 1.0 / (2 * side) * 0.99\n>>>>>>> REPLACE"


def _mock_response(content: str):
    body = json.dumps({"choices": [{"message": {"content": content}}]}).encode()
    cm = MagicMock()
    cm.__enter__.return_value.read.return_value = body
    return cm


def _mock_response_raw(payload: dict):
    cm = MagicMock()
    cm.__enter__.return_value.read.return_value = json.dumps(payload).encode()
    return cm


# --- prompt building (pure, no network) --------------------------------

def test_build_messages_includes_task_and_source():
    msgs = build_messages(task=TASK, parent_src="def candidate_packing(n): pass", prior_rejection=None)
    assert msgs[0]["role"] == "system"
    assert TASK.block_name in msgs[0]["content"]
    assert "candidate_packing" in msgs[1]["content"]
    assert "rejected" not in msgs[1]["content"].lower()


def test_build_messages_includes_prior_rejection_feedback():
    msgs = build_messages(
        task=TASK, parent_src="src",
        prior_rejection={"code": "E_CONTRACT_VIOLATION", "message": "signature changed"},
    )
    assert "E_CONTRACT_VIOLATION" in msgs[1]["content"]
    assert "signature changed" in msgs[1]["content"]


# --- client, network mocked --------------------------------------------

def test_propose_diff_happy_path(tmp_path):
    client = SigmaClient(api_key="test-key", budget_path=tmp_path / "b.json")
    with patch("sigma.client.urllib.request.urlopen", return_value=_mock_response(GOOD_DIFF)):
        diff = client.propose_diff(task=TASK, parent_src="src")
    assert diff == GOOD_DIFF


def test_propose_diff_rejects_response_with_no_hunk(tmp_path):
    client = SigmaClient(api_key="test-key", budget_path=tmp_path / "b.json")
    with patch("sigma.client.urllib.request.urlopen", return_value=_mock_response("sorry, I can't do that")):
        with pytest.raises(SigmaError, match="no SEARCH/REPLACE hunk"):
            client.propose_diff(task=TASK, parent_src="src")


def test_propose_diff_finds_hunk_even_inside_markdown_fence(tmp_path):
    fenced = f"```diff\n{GOOD_DIFF}\n```"
    client = SigmaClient(api_key="test-key", budget_path=tmp_path / "b.json")
    with patch("sigma.client.urllib.request.urlopen", return_value=_mock_response(fenced)):
        diff = client.propose_diff(task=TASK, parent_src="src")
    assert "<<<<<<< SEARCH" in diff  # passed through as-is; apply_bounded_diff finds it regardless


def test_missing_api_key_raises_clear_error(tmp_path, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(SigmaError, match="GROQ_API_KEY"):
        SigmaClient(budget_path=tmp_path / "b.json")


def test_daily_budget_enforced_before_network_call(tmp_path):
    client = SigmaClient(api_key="test-key", daily_request_cap=1, budget_path=tmp_path / "b.json")
    with patch("sigma.client.urllib.request.urlopen", return_value=_mock_response(GOOD_DIFF)) as mock_open:
        client.propose_diff(task=TASK, parent_src="src")
        with pytest.raises(BudgetExceeded):
            client.propose_diff(task=TASK, parent_src="src")
    assert mock_open.call_count == 1  # second call never reached the network


def test_429_retries_then_succeeds(tmp_path):
    client = SigmaClient(api_key="test-key", budget_path=tmp_path / "b.json")
    rate_limited = urllib.error.HTTPError(
        url="https://api.groq.com/openai/v1/chat/completions", code=429, msg="Too Many Requests",
        hdrs={"Retry-After": "0.01"}, fp=io.BytesIO(b'{"error":"rate limited"}'),
    )
    with patch("sigma.client.urllib.request.urlopen", side_effect=[rate_limited, _mock_response(GOOD_DIFF)]):
        with patch("sigma.client.time.sleep"):  # don't actually wait in tests
            diff = client.propose_diff(task=TASK, parent_src="src")
    assert diff == GOOD_DIFF


def test_non_retryable_http_error_raises_immediately(tmp_path):
    client = SigmaClient(api_key="bad-key", budget_path=tmp_path / "b.json")
    auth_error = urllib.error.HTTPError(
        url="https://api.groq.com/openai/v1/chat/completions", code=401, msg="Unauthorized",
        hdrs={}, fp=io.BytesIO(b'{"error":"invalid api key"}'),
    )
    with patch("sigma.client.urllib.request.urlopen", side_effect=auth_error):
        with pytest.raises(SigmaError, match="401"):
            client.propose_diff(task=TASK, parent_src="src")


def test_request_carries_a_non_default_user_agent(tmp_path):
    """Regression test: Cloudflare fronts api.groq.com and 403s the
    default Python-urllib User-Agent (error code 1010) before the request
    reaches Groq's own API layer at all. Confirmed against the live API --
    see the chat transcript for the exact traceback this guards against."""
    client = SigmaClient(api_key="test-key", budget_path=tmp_path / "b.json")
    captured = {}

    def _capture_and_respond(req, timeout=None):
        captured["headers"] = dict(req.headers)
        return _mock_response(GOOD_DIFF)

    with patch("sigma.client.urllib.request.urlopen", side_effect=_capture_and_respond):
        client.propose_diff(task=TASK, parent_src="src")

    ua = captured["headers"].get("User-agent")  # urllib title-cases header keys
    assert ua is not None
    assert "python-urllib" not in ua.lower()


def test_reasoning_effort_sent_for_gpt_oss_model(tmp_path):
    """Regression test: gpt-oss-120b defaults to medium reasoning effort,
    which can consume the entire max_tokens budget on chain-of-thought
    before writing anything into `content` -- confirmed live (empty
    content, finish_reason="length"). Low effort is the fix for a task
    this simple."""
    client = SigmaClient(api_key="test-key", model="openai/gpt-oss-120b", budget_path=tmp_path / "b.json")
    captured = {}

    def _capture_and_respond(req, timeout=None):
        captured["body"] = json.loads(req.data)
        return _mock_response(GOOD_DIFF)

    with patch("sigma.client.urllib.request.urlopen", side_effect=_capture_and_respond):
        client.propose_diff(task=TASK, parent_src="src")

    assert captured["body"]["reasoning_effort"] == "low"


def test_reasoning_effort_omitted_for_non_reasoning_model(tmp_path):
    """Sending reasoning_effort to a model that doesn't support it risks
    an unrelated 400 -- only gate it on for the gpt-oss family."""
    client = SigmaClient(api_key="test-key", model="some-other-model", budget_path=tmp_path / "b.json")
    captured = {}

    def _capture_and_respond(req, timeout=None):
        captured["body"] = json.loads(req.data)
        return _mock_response(GOOD_DIFF)

    with patch("sigma.client.urllib.request.urlopen", side_effect=_capture_and_respond):
        client.propose_diff(task=TASK, parent_src="src")

    assert "reasoning_effort" not in captured["body"]


def test_empty_content_from_reasoning_exhaustion_gives_clear_diagnostic(tmp_path):
    """Regression test for the exact live failure: reasoning tokens ate the
    whole budget, content came back "" with finish_reason="length". The
    error message must say WHY, not just that no hunk was found in ''."""
    client = SigmaClient(api_key="test-key", budget_path=tmp_path / "b.json")
    payload = {
        "choices": [{"message": {"content": ""}, "finish_reason": "length"}],
        "usage": {"completion_tokens": 2048, "completion_tokens_details": {"reasoning_tokens": 2048}},
    }
    with patch("sigma.client.urllib.request.urlopen", return_value=_mock_response_raw(payload)):
        with pytest.raises(SigmaError, match="reasoning"):
            client.propose_diff(task=TASK, parent_src="src")


# --- Week 3 Day 16: usage logging, daily-limit 429, proposal errors ---------

from sigma.client import SigmaProposalError  # noqa: E402


def _with_usage(content, prompt=900, completion=400, reasoning=250):
    return {
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": prompt, "completion_tokens": completion,
                  "total_tokens": prompt + completion,
                  "completion_tokens_details": {"reasoning_tokens": reasoning}},
    }


def test_usage_is_logged_and_added_to_the_daily_token_tally(tmp_path):
    client = SigmaClient(api_key="k", budget_path=tmp_path / "b.json")
    with patch("sigma.client.urllib.request.urlopen", return_value=_mock_response_raw(_with_usage(GOOD_DIFF))):
        client.propose_diff(task=TASK, parent_src="src")
    assert client.budget.tokens_used() == 1300
    rows = [json.loads(line) for line in client.usage_log_path.read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]["total_tokens"] == 1300 and rows[0]["reasoning_tokens"] == 250
    assert client.usage_log_path.parent == tmp_path  # never leaks into the real home dir under test


def test_usage_is_recorded_even_when_the_reply_is_empty(tmp_path):
    """A reasoning-exhausted empty reply still burned tokens against TPD."""
    client = SigmaClient(api_key="k", budget_path=tmp_path / "b.json")
    payload = _with_usage("", prompt=900, completion=2048, reasoning=2048)
    payload["choices"][0]["finish_reason"] = "length"
    with patch("sigma.client.urllib.request.urlopen", return_value=_mock_response_raw(payload)):
        with pytest.raises(SigmaProposalError):
            client.propose_diff(task=TASK, parent_src="src")
    assert client.budget.tokens_used() == 2948


def test_response_without_usage_block_does_not_break_logging(tmp_path):
    client = SigmaClient(api_key="k", budget_path=tmp_path / "b.json")
    with patch("sigma.client.urllib.request.urlopen", return_value=_mock_response(GOOD_DIFF)):
        client.propose_diff(task=TASK, parent_src="src")
    assert client.budget.tokens_used() == 0 and not client.usage_log_path.exists()


def test_local_token_cap_stops_before_the_network(tmp_path):
    client = SigmaClient(api_key="k", budget_path=tmp_path / "b.json", daily_token_cap=1000)
    with patch("sigma.client.urllib.request.urlopen", return_value=_mock_response_raw(_with_usage(GOOD_DIFF))) as m:
        client.propose_diff(task=TASK, parent_src="src")  # 1300 tokens > cap
        with pytest.raises(BudgetExceeded):
            client.propose_diff(task=TASK, parent_src="src")
    assert m.call_count == 1


def _http_429(body: bytes, retry_after: str):
    return urllib.error.HTTPError(
        url="https://api.groq.com/openai/v1/chat/completions", code=429, msg="Too Many Requests",
        hdrs={"Retry-After": retry_after}, fp=io.BytesIO(body),
    )


def test_daily_token_429_becomes_budget_exceeded_without_sleeping(tmp_path):
    client = SigmaClient(api_key="k", budget_path=tmp_path / "b.json")
    body = b'{"error":{"message":"Rate limit reached ... on tokens per day (TPD): Limit 200000, Used 199900"}}'
    with patch("sigma.client.urllib.request.urlopen", side_effect=_http_429(body, "30")):
        with patch("sigma.client.time.sleep") as sleep:
            with pytest.raises(BudgetExceeded, match="per day"):
                client.propose_diff(task=TASK, parent_src="src")
    sleep.assert_not_called()


def test_429_with_a_very_long_retry_after_is_treated_as_a_daily_limit(tmp_path):
    client = SigmaClient(api_key="k", budget_path=tmp_path / "b.json")
    with patch("sigma.client.urllib.request.urlopen", side_effect=_http_429(b'{"error":"limit"}', "3600")):
        with patch("sigma.client.time.sleep") as sleep:
            with pytest.raises(BudgetExceeded):
                client.propose_diff(task=TASK, parent_src="src")
    sleep.assert_not_called()


def test_per_minute_429_is_still_retried(tmp_path):
    client = SigmaClient(api_key="k", budget_path=tmp_path / "b.json")
    body = b'{"error":{"message":"Rate limit reached on tokens per minute (TPM)"}}'
    with patch("sigma.client.urllib.request.urlopen", side_effect=[_http_429(body, "2"), _mock_response(GOOD_DIFF)]):
        with patch("sigma.client.time.sleep") as sleep:
            assert client.propose_diff(task=TASK, parent_src="src") == GOOD_DIFF
    sleep.assert_called_once_with(2.0)


def test_unusable_replies_are_proposal_errors_but_auth_errors_are_not(tmp_path):
    client = SigmaClient(api_key="k", budget_path=tmp_path / "b.json")
    with patch("sigma.client.urllib.request.urlopen", return_value=_mock_response("no diff here")):
        with pytest.raises(SigmaProposalError):
            client.propose_diff(task=TASK, parent_src="src")
    auth = urllib.error.HTTPError("u", 401, "Unauthorized", {}, io.BytesIO(b"{}"))
    with patch("sigma.client.urllib.request.urlopen", side_effect=auth):
        with pytest.raises(SigmaError) as ei:
            client.propose_diff(task=TASK, parent_src="src")
    assert not isinstance(ei.value, SigmaProposalError)  # must still crash the run loudly
