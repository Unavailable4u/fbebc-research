# delta/orchestrator.py
#
# Wires the six-gate admission pipeline (Phase1 guide §6) out of the Week 1
# pieces. Nothing here reimplements a gate -- it only sequences the
# already-built, already-tested functions in the order the guide specifies,
# cheapest-first, and translates each failure into either a typed
# AdmissionError (feedback-worthy, goes back to Sigma) or an
# IntegrityViolation (fatal, halts the run, Appendix B: "Halt-the-run").
#
# Gate-by-gate mapping to existing Week 1 code:
#   G0 Parse     -> enforced INSIDE apply_bounded_diff (admission/applicator.py)
#   G1 Boundary  -> enforced INSIDE apply_bounded_diff, same call
#                   (its post-conditions -- byte-identical immutable regions,
#                   invariant marker set -- ARE G0/G1; see that file's
#                   docstring: "It does not trust its own patching logic;
#                   it trusts the post-condition.")
#   G2 Contract  -> admission/contracts.py: verify_contract()
#   G3 Capability -> admission/static_gate.py: check_block()
#                    (telemetry/efficiency filter, NOT a security boundary --
#                    see that file's own docstring; the kernel is the real
#                    boundary, enforced later at container launch)
#   G4 Budget-measure -> admission/metrics.py: edit_metrics()
#                    Recorded, NOT enforced (research-program-guide §1.4,
#                    Week 2 Day 10-11: "skip G4's fairness threshold ...
#                    you still record the edit-distance metric, you just
#                    don't reject on it yet").
#   G5 Integrity -> integrity/manifest.py: verify()
#                    Immediately before anything is admitted for evaluation.

from pathlib import Path

from .admission.applicator import apply_bounded_diff
from .admission.contracts import verify_contract
from .admission.errors import AdmissionError
from .admission.metrics import edit_metrics
from .admission.static_gate import CapabilityDenied, check_block
from .admission.tasks import TaskSpec
from .integrity import manifest as manifest_mod

# Phase1 §6's rule for what Sigma is allowed to see about a rejection:
# describe what was wrong with ITS diff, never how the gate that caught it
# works internally (no file/line of our own code, no mention of which
# check ran). Every detail string currently produced across applicator.py /
# contracts.py / static_gate.py already describes the candidate's OWN diff
# (e.g. "SEARCH matches only outside an EVOLVE-BLOCK") rather than gate
# internals, so passing exc.detail through is safe today. If you add a new
# gate message later, keep that property.
_HUMAN_PREFIX = {
    "E_MALFORMED_DIFF": "Diff format problem",
    "E_SYNTAX": "The edited code has a syntax error",
    "E_BOUNDARY_VIOLATION": "Your edit touched text outside the allowed block",
    "E_MARKER_FORGERY": "Your edit altered a block marker",
    "E_AMBIGUOUS_MATCH": "Your SEARCH text matched more than one location",
    "E_CONTRACT_VIOLATION": "Your edit changed the function's fixed signature or contract",
    "E_CAPABILITY_DENIED": "Your edit used a capability that isn't allowed here",
}


def sanitize_rejection(exc: AdmissionError) -> dict:
    """Render an AdmissionError as {"code": str, "message": str} suitable
    for sigma.prompts.build_messages()'s prior_rejection argument."""
    prefix = _HUMAN_PREFIX.get(exc.code, "Your proposal was rejected")
    return {"code": exc.code, "message": f"{prefix}: {exc.detail}"}


def admit_candidate(
    *,
    parent_src: str,
    diff_text: str,
    task: TaskSpec,
    p0_src: str,
    expected_manifest: dict,
    manifest_roots: list[Path],
    strict_soft: bool = False,
) -> dict:
    """Run one Sigma proposal through G0-G5.

    Returns an admission record dict on success:
        {"admitted": True, "child_src": str, "metrics": dict, "soft_hits": list}

    Raises:
        AdmissionError        -- G0-G3 rejection. Typed, sanitized feedback
                                  goes back to Sigma in the next prompt
                                  (Phase1 §6: never echo gate internals).
        manifest_mod.IntegrityViolation
                               -- G5 failure. NOT Sigma's fault, NOT returned
                                  as feedback. The caller must halt the run,
                                  mark the current generation and all
                                  descendants UNATTESTED, and dump a
                                  forensic bundle (Phase1 §5).
    """
    # G0 (parse) + G1 (boundary): see module docstring for why one call
    # covers both.
    child_src = apply_bounded_diff(parent_src, diff_text)

    # G2 (contract)
    verify_contract(parent_src, child_src, set(task.pinned_names))

    # G3 (capability) -- CapabilityDenied is static_gate.py's own exception
    # type; translate it into the shared AdmissionError taxonomy so every
    # gate's failure looks the same to the caller and to the ledger.
    try:
        gate_result = check_block(child_src, strict_soft=strict_soft)
    except CapabilityDenied as e:
        raise AdmissionError("E_CAPABILITY_DENIED", str(e)) from e

    # G4 (budget-measure) -- recorded, not enforced, in Stage 1.
    metrics = edit_metrics(parent_src, child_src, p0_src)

    # G5 (integrity re-check) -- the last thing that happens before a
    # candidate is admitted for evaluation. This checks that Delta itself
    # (this code, not the candidate) hasn't been tampered with since
    # expected_manifest was captured.
    manifest_mod.verify(expected_manifest, manifest_roots)

    return {
        "admitted": True,
        "child_src": child_src,
        "metrics": metrics,
        "soft_hits": gate_result["soft_hits"],
    }
