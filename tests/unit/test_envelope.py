import math

import pytest

from delta.evaluation.envelope import (
    AttestationFailure,
    SchemaViolation,
    validate_outputs,
)


def test_clean_binpacking_output_ok():
    validate_outputs({"results": [{"instance_id": "bp-0000", "solution": [0, 0, 1]}]})


def test_clean_circle_packing_output_ok():
    validate_outputs({"circles": [[0.1, 0.1, 0.05], [0.5, 0.5, 0.1]]})


def test_none_outputs_is_attestation_failure():
    with pytest.raises(AttestationFailure):
        validate_outputs(None)


@pytest.mark.parametrize("key", ["score", "fitness", "reward", "rank", "elite", "passed"])
def test_score_like_key_rejected_at_any_depth(key):
    with pytest.raises(SchemaViolation):
        validate_outputs({"results": [{"instance_id": "x", key: 1.0}]})


def test_score_like_key_at_top_level_rejected():
    with pytest.raises(SchemaViolation):
        validate_outputs({"score": 1.0})


def test_nan_rejected():
    with pytest.raises(AttestationFailure):
        validate_outputs({"circles": [[0.1, 0.1, float("nan")]]})


def test_inf_rejected():
    with pytest.raises(AttestationFailure):
        validate_outputs({"circles": [[0.1, 0.1, math.inf]]})


def test_rigged_float_subclass_stripped_and_checked():
    class Rigged(float):
        def __gt__(self, other):
            return True  # always claims to be bigger, regardless of value

    # A finite rigged value should NOT raise -- float() strips the subclass
    # but the underlying value is still legitimate.
    validate_outputs({"circles": [[0.1, 0.1, Rigged(0.05)]]})

    # A non-finite rigged value should still be caught.
    with pytest.raises(AttestationFailure):
        validate_outputs({"circles": [[0.1, 0.1, Rigged("nan")]]})


def test_bool_is_not_treated_as_forbidden_numeric():
    # bool is an int subclass; make sure it doesn't spuriously trip anything.
    validate_outputs({"results": [{"instance_id": "x", "valid_shape": True}]})
