import pytest

from delta.admission.contracts import verify_contract
from delta.admission.errors import AdmissionError

PARENT = """\
import math

def candidate_solver(x: int, rng) -> list:
    return [x]
"""


def test_identical_contract_ok():
    verify_contract(PARENT, PARENT, {"candidate_solver"})


def test_body_only_change_ok():
    child = PARENT.replace("return [x]", "return [x, x]")
    verify_contract(PARENT, child, {"candidate_solver"})  # should not raise


def test_added_default_argument_rejected():
    child = PARENT.replace(
        "def candidate_solver(x: int, rng) -> list:",
        "def candidate_solver(x: int, rng, extra=1) -> list:",
    )
    with pytest.raises(AdmissionError) as exc:
        verify_contract(PARENT, child, {"candidate_solver"})
    assert exc.value.code == "E_CONTRACT_VIOLATION"


def test_removed_pinned_function_rejected():
    child = "import math\n\ndef something_else():\n    return 1\n"
    with pytest.raises(AdmissionError) as exc:
        verify_contract(PARENT, child, {"candidate_solver"})
    assert exc.value.code == "E_CONTRACT_VIOLATION"


def test_new_import_rejected():
    child = "import math\nimport os\n\n" + "\n".join(PARENT.splitlines()[2:])
    with pytest.raises(AdmissionError) as exc:
        verify_contract(PARENT, child, {"candidate_solver"})
    assert exc.value.code == "E_CONTRACT_VIOLATION"


def test_return_annotation_change_rejected():
    child = PARENT.replace(
        "def candidate_solver(x: int, rng) -> list:",
        "def candidate_solver(x: int, rng) -> dict:",
    )
    with pytest.raises(AdmissionError) as exc:
        verify_contract(PARENT, child, {"candidate_solver"})
    assert exc.value.code == "E_CONTRACT_VIOLATION"
