# delta/admission/errors.py
#
# The Phase 1 guide defines `AdmissionError` inline inside applicator.py
# (§7.2) but contracts.py (§7.3) also raises it without importing it, and
# Appendix B's rejection taxonomy treats all E_* codes as one family shared
# across G0-G5. We factor it out here so every gate module imports the same
# class instead of each redefining its own — a faithful-intent fix, not a
# scope change.

# Appendix B — Rejection taxonomy (Tiers A/C only are in Stage 1's ADV scope
# per research-program-guide §1.1, but every gate still emits its typed code
# regardless of which ADV tier later exercises it).
REJECTION_TAXONOMY = {
    "E_MALFORMED_DIFF": "G0",
    "E_SYNTAX": "G0",
    "E_BOUNDARY_VIOLATION": "G1",
    "E_MARKER_FORGERY": "G1",
    "E_AMBIGUOUS_MATCH": "G1",
    "E_CONTRACT_VIOLATION": "G2",
    "E_CAPABILITY_DENIED": "G3",
    "E_BUDGET_EXCEEDED": "G4",
    "E_INTEGRITY_VIOLATION": "G5",
    "E_SCHEMA_VIOLATION": "post",
    "E_ATTESTATION_FAILURE": "post",
    "E_TIMING_ANOMALY": "post",
}

# Rejection codes that count as a "barrier event" per Appendix B — the
# denominator that matters for the ADV suite's pass/fail claim.
BARRIER_EVENT_CODES = {
    "E_BOUNDARY_VIOLATION",
    "E_MARKER_FORGERY",
    "E_CONTRACT_VIOLATION",
    "E_SCHEMA_VIOLATION",
    "E_ATTESTATION_FAILURE",
    "E_TIMING_ANOMALY",
}


class AdmissionError(ValueError):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail
