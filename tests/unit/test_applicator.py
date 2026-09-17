import pytest

from delta.admission.applicator import apply_bounded_diff
from delta.admission.errors import AdmissionError

SRC = """\
import math

# EVOLVE-BLOCK-START: core
def f(x):
    return x + 1
# EVOLVE-BLOCK-END: core

def untouchable():
    return "boilerplate"
"""


def _diff(search: str, replace: str) -> str:
    return f"<<<<<<< SEARCH\n{search}\n=======\n{replace}\n>>>>>>> REPLACE"


def test_valid_diff_applies():
    diff = _diff("    return x + 1", "    return x + 2")
    out = apply_bounded_diff(SRC, diff)
    assert "return x + 2" in out
    assert "def untouchable" in out  # boilerplate untouched


def test_edit_outside_block_rejected():
    # A01/A02-style attack: SEARCH text matches only in the immutable region.
    diff = _diff('    return "boilerplate"', '    return "hacked"')
    with pytest.raises(AdmissionError) as exc:
        apply_bounded_diff(SRC, diff)
    assert exc.value.code == "E_BOUNDARY_VIOLATION"


def test_marker_injection_rejected():
    # A03-style attack: widen the mutable zone by injecting a new START marker
    # inside the body, immediately followed by more of the boilerplate so the
    # post-condition (block set/order unchanged) catches the escalation.
    search = "    return x + 1"
    replace = (
        "    return x + 1\n"
        "# EVOLVE-BLOCK-END: core\n"
        "# EVOLVE-BLOCK-START: core\n"
        "def untouchable():\n"
        '    return "hacked"'
    )
    diff = _diff(search, replace)
    with pytest.raises(AdmissionError) as exc:
        apply_bounded_diff(SRC, diff)
    assert exc.value.code in ("E_MARKER_FORGERY", "E_BOUNDARY_VIOLATION")


def test_ambiguous_search_rejected():
    src = """\
# EVOLVE-BLOCK-START: core
def f(x):
    return x
def g(x):
    return x
# EVOLVE-BLOCK-END: core
"""
    diff = _diff("    return x", "    return x * 2")
    with pytest.raises(AdmissionError) as exc:
        apply_bounded_diff(src, diff)
    assert exc.value.code == "E_AMBIGUOUS_MATCH"


def test_search_not_found_rejected():
    diff = _diff("    return x + 999", "    return x + 2")
    with pytest.raises(AdmissionError) as exc:
        apply_bounded_diff(SRC, diff)
    assert exc.value.code == "E_MALFORMED_DIFF"


def test_no_hunk_rejected():
    with pytest.raises(AdmissionError) as exc:
        apply_bounded_diff(SRC, "not a diff at all")
    assert exc.value.code == "E_MALFORMED_DIFF"


def test_empty_search_rejected():
    diff = _diff("", "    return 0")
    with pytest.raises(AdmissionError) as exc:
        apply_bounded_diff(SRC, diff)
    assert exc.value.code == "E_MALFORMED_DIFF"


def test_syntax_error_after_patch_rejected():
    diff = _diff("    return x + 1", "    return x +")
    with pytest.raises(AdmissionError) as exc:
        apply_bounded_diff(SRC, diff)
    assert exc.value.code == "E_SYNTAX"


def test_multi_hunk_diff_applies_in_order():
    diff = (
        _diff("    return x + 1", "    return x + 2")
        + "\n"
        + _diff("def f(x):", "def f(x):  # renamed comment ok")
    )
    out = apply_bounded_diff(SRC, diff)
    assert "return x + 2" in out
    assert "renamed comment ok" in out
