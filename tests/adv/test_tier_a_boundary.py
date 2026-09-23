# tests/adv/test_tier_a_boundary.py
#
# Tier A (structural boundary) cases from the Phase 1 guide's Appendix B
# 24-case table (§13.1), scoped down to Stage 1's "Tiers A and C" cut
# (research-program-guide §1.1). A01-A06 already have equivalent coverage
# in tests/unit/test_applicator.py and tests/unit/test_contracts.py -- see
# tests/adv/COVERAGE.md for the full case-by-case mapping. This file adds
# the one Tier A case with no existing test: A07.

import pytest

from delta.admission.applicator import apply_bounded_diff
from delta.admission.errors import AdmissionError

SRC = """\
# EVOLVE-BLOCK-START: core
def f(x):
    return x + 1
# EVOLVE-BLOCK-END: core
"""


def _diff(search: str, replace: str) -> str:
    return f"<<<<<<< SEARCH\n{search}\n=======\n{replace}\n>>>>>>> REPLACE"


def test_a07_unicode_homoglyph_identifier_rejected():
    """A07: syntactically-plausible but non-ASCII identifiers. Cyrillic 'х'
    (U+0445) looks identical to Latin 'x' in most fonts/terminals but is a
    different codepoint, so this defines a SECOND function that only looks
    like a redefinition of `f`. Python happily parses this (identifiers
    can be non-ASCII) -- the guide's expected outcome is "parse or
    canonicalization fails OR clean reject", i.e. this must not silently
    admit a shadow function under a confusable name.
    """
    homoglyph_x = "\u0445"  # CYRILLIC SMALL LETTER HA, not Latin x
    replace = (
        "    return x + 1\n"
        f"def f(x, {homoglyph_x}=None):\n"
        f"    return {homoglyph_x} or x"
    )
    diff = _diff("    return x + 1", replace)
    # This diff redefines `f` a second time inside the block, which is
    # syntactically legal Python (last definition wins) but MUST be caught
    # somewhere before evaluation -- either by G2's signature pin (the
    # contract is keyed on the qualified name `f`, and a re-`def f` changes
    # its own signature/default set relative to the parent) or it must at
    # least be forced through the normal gate path rather than silently
    # bypassing it. We assert it does NOT apply silently.
    try:
        result = apply_bounded_diff(SRC, diff)
    except AdmissionError:
        return  # rejected at the applicator level -- acceptable outcome
    # If the applicator allowed it (it's boundary-legal: all inside the
    # block), the contract gate must be the backstop. Confirm the emitted
    # source actually contains two `def f` -- i.e. we understand what we're
    # testing -- then confirm contracts.py flags it.
    assert result.count("def f(") == 2
    from delta.admission.contracts import verify_contract
    with pytest.raises(AdmissionError) as exc:
        verify_contract(SRC, result, {"f"})
    assert exc.value.code == "E_CONTRACT_VIOLATION"


def test_a07_confusable_identifier_does_not_alias_pinned_name():
    """A softer A07 variant: renaming the pinned function using a
    homoglyph so `candidate_solver` (Latin) and a homoglyph twin coexist.
    G2 pins the exact qualified name, so a homoglyph twin is just a NEW,
    unpinned function -- it must not be mistaken for satisfying the pin."""
    src = """\
# EVOLVE-BLOCK-START: core
def candidate_solver(x):
    return x
# EVOLVE-BLOCK-END: core
"""
    homoglyph_name = "candidate_s\u043elver"  # Cyrillic 'о' (U+043E) for Latin 'o'
    diff = _diff(
        "def candidate_solver(x):\n    return x",
        f"def candidate_solver(x):\n    return x\ndef {homoglyph_name}(x):\n    return x * 2",
    )
    result = apply_bounded_diff(src, diff)
    from delta.admission.contracts import qualified_signatures
    sigs = qualified_signatures(result)
    # The real pinned name must still be present and unchanged; the
    # homoglyph twin existing alongside it is fine -- it's just dead code
    # from the candidate's perspective, since nothing calls it.
    assert "candidate_solver" in sigs
    assert homoglyph_name in sigs
    assert homoglyph_name != "candidate_solver"  # i.e. they are NOT confused as the same key
