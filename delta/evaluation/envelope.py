# delta/evaluation/envelope.py
#
# Phase1 §9.2's schema rule, made task-agnostic: "The absence of a `score`
# field is a schema invariant, not a convention." This walks a candidate's
# raw `outputs` dict BEFORE any task-specific scorer touches it, so both
# Stage 1 tasks (binpacking, circle_packing) get the same I3 (score
# non-authorship) defense for free instead of each scorer reimplementing it.
#
# Two checks, matching Appendix B's two "post" rejection codes:
#   E_SCHEMA_VIOLATION     -- outputs contain a score-like key. Per Phase1
#                             §6: "a candidate that emits a `score` key is
#                             not confused -- it is trying." (ADV C02-style.)
#   E_ATTESTATION_FAILURE  -- outputs contain a non-finite number, or a
#                             number that only survives naive comparison
#                             because it's a rigged subclass (ADV C05).
#                             float(x) strips any such subclass; this is
#                             the same coercion Phase1 §9.3's
#                             `_finite_number` uses, just applied generically
#                             across the whole outputs tree instead of one
#                             named field.
#
# Deliberately NOT ported from Phase1 §9.3: the timing cross-check
# (`drift`/`timing_anomaly`). That defends the *latency* channel from
# tampering (ADV C01), and Stage 1 has no latency in its fitness function
# (research-program-guide §1.1) -- there is no timing signal left to
# protect, so building the cross-check would be adding back exactly the
# kind of cost the guide's scope cut exists to avoid. This is a disclosed
# exclusion, not an oversight: state it in the paper's ADV-suite-scope
# paragraph alongside the Tier A/C selection rationale.

import math

FORBIDDEN_KEYS = {"score", "fitness", "reward", "rank", "elite", "passed"}


class SchemaViolation(Exception):
    code = "E_SCHEMA_VIOLATION"


class AttestationFailure(Exception):
    code = "E_ATTESTATION_FAILURE"


def _scan(obj, path: str = "<root>") -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in FORBIDDEN_KEYS:
                raise SchemaViolation(f"forbidden key {k!r} at {path}")
            _scan(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _scan(v, f"{path}[{i}]")
    elif isinstance(obj, bool):
        pass  # bool is an int subclass; explicitly not a numeric leaf here
    elif isinstance(obj, (int, float)):
        v = float(obj)  # strips a rigged __gt__/__eq__ subclass (ADV C05)
        if not math.isfinite(v):
            raise AttestationFailure(f"non-finite value at {path}")


def validate_outputs(outputs) -> None:
    """Raises SchemaViolation or AttestationFailure; returns None if clean.

    Called on the raw `outputs` field of a supervisor envelope, before any
    task-specific scorer runs.
    """
    if outputs is None:
        raise AttestationFailure("no parseable outputs")
    _scan(outputs)
