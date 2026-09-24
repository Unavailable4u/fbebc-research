# Prompt v2 (Day 16). The wording itself is a research decision recorded in
# PREREGISTRATION.md §7; these tests pin the properties that decision relies on.

from delta.admission.tasks import get_task
from sigma import prompts
from sigma.prompts import PROMPT_VERSION, SYSTEM_PROMPT, TASK_OBJECTIVES, build_messages, prompt_fingerprint

TASK = get_task("circle_packing")


def test_version_is_v2():
    assert PROMPT_VERSION == "v2"


def test_circle_objective_states_the_all_or_nothing_validity_rule_and_unequal_radii():
    obj = TASK_OBJECTIVES["circle_packing"].lower()
    assert "any circle" in obj and "scores 0" in obj
    assert "differ" in obj


def test_edit_size_is_no_longer_restricted_to_small_edits():
    assert "small, targeted" not in SYSTEM_PROMPT
    assert "rewriting the whole body" in SYSTEM_PROMPT


def test_prompt_never_leaks_gate_internals_or_mentions_rejection_without_one():
    msgs = build_messages(task=TASK, parent_src="src", prior_rejection=None)
    assert "rejected" not in msgs[1]["content"].lower()  # no rejection feedback unless there was one


def test_hard_format_rules_are_still_present():
    for needle in ("EVOLVE-BLOCK-START", "<<<<<<< SEARCH", ">>>>>>> REPLACE", "EXACTLY ONE hunk"):
        assert needle in SYSTEM_PROMPT


def test_fingerprint_is_stable_and_changes_when_any_prompt_text_changes(monkeypatch):
    base = prompt_fingerprint()
    assert base == prompt_fingerprint() and len(base) == 64
    monkeypatch.setattr(prompts, "SYSTEM_PROMPT", SYSTEM_PROMPT + " x")
    assert prompt_fingerprint() != base
    monkeypatch.undo()
    monkeypatch.setitem(prompts.TASK_OBJECTIVES, "circle_packing", "changed")
    assert prompt_fingerprint() != base
