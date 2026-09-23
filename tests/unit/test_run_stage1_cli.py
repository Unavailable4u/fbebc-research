# Only the pure, no-network helper from scripts/run_stage1.py is unit
# tested here. The rest of that file constructs a real SigmaClient (needs
# GROQ_API_KEY) and a real Docker sandbox -- exercised for real on your own
# machine per WEEK3_SETUP.md, not here (same split as sigma/client.py's
# own docstring: "run python -m sigma.client first thing ... to catch
# anything that only shows up against the live API").

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_run_stage1():
    spec = importlib.util.spec_from_file_location("run_stage1", REPO_ROOT / "scripts" / "run_stage1.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["run_stage1"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_single_seed_ledger_path_is_unchanged():
    mod = _load_run_stage1()
    assert mod._ledger_path_for_seed("run_ledger.db", 0, multi=False) == "run_ledger.db"


def test_multi_seed_ledger_path_gets_seed_suffix_before_extension():
    mod = _load_run_stage1()
    assert mod._ledger_path_for_seed("run_ledger.db", 1000, multi=True) == "run_ledger.seed1000.db"


def test_multi_seed_ledger_path_respects_directory():
    mod = _load_run_stage1()
    path = str(REPO_ROOT / "runs" / "week3.db")
    expected = str(REPO_ROOT / "runs" / "week3.seed7.db")
    assert mod._ledger_path_for_seed(path, 7, multi=True) == expected
