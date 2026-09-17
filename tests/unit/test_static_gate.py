import pytest

from delta.admission.static_gate import check_block, CapabilityDenied


def test_clean_code_passes():
    result = check_block("def f(x):\n    return x + 1\n")
    assert result["soft_hits"] == []


def test_forbidden_import_denied():
    with pytest.raises(CapabilityDenied):
        check_block("import os\n")


def test_forbidden_import_from_denied():
    with pytest.raises(CapabilityDenied):
        check_block("from subprocess import run\n")


def test_forbidden_name_eval_denied():
    with pytest.raises(CapabilityDenied):
        check_block("eval('1+1')\n")


def test_forbidden_attribute_denied():
    with pytest.raises(CapabilityDenied):
        check_block("def f(fn):\n    return fn.__globals__\n")


def test_global_statement_denied():
    with pytest.raises(CapabilityDenied):
        check_block("def f():\n    global x\n    x = 1\n")


def test_soft_name_recorded_not_denied_by_default():
    result = check_block("def f(o):\n    return getattr(o, 'x')\n")
    assert len(result["soft_hits"]) == 1
    assert result["soft_hits"][0][0] == "getattr"


def test_soft_name_denied_in_strict_mode():
    with pytest.raises(CapabilityDenied):
        check_block("def f(o):\n    return getattr(o, 'x')\n", strict_soft=True)
