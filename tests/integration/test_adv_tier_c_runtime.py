# tests/integration/test_adv_tier_c_runtime.py
#
# Tier C (reward hacking) cases from the Phase 1 guide's Appendix B (§13.1)
# that specifically need a REAL container lifecycle to mean anything --
# C04 (does state survive across separate `docker run` invocations?) can't
# be answered by a unit test, it has to be answered by actually running two
# containers. C06 and C10 could technically be exercised by calling
# harness/supervisor.py's run_once() directly, but that function hardcodes
# container-internal absolute paths (/work, /harness) by design (Phase1
# §8.3) -- rerouting those for a host-only test would mean testing a
# different code path than what actually runs in production. Going through
# run_in_sandbox() for all three keeps this file honest about what it's
# actually proving.
#
# Same requires-docker skip as test_sandbox_smoke.py. See
# tests/adv/COVERAGE.md for the full case-by-case mapping.

import json
import shutil

import pytest

from delta.evaluation.launcher import run_in_sandbox

pytestmark = pytest.mark.skipif(
    shutil.which("docker") is None, reason="requires a real Docker daemon"
)


def _work_dir(tmp_path, candidate_src: str, task_input: dict):
    d = tmp_path / "work"
    d.mkdir()
    (d / "candidate.py").write_text(candidate_src, encoding="utf-8")
    (d / "task_input.json").write_text(json.dumps(task_input), encoding="utf-8")
    return d


def test_c04_state_does_not_survive_across_separate_container_runs(tmp_path):
    """C04: memoize results across runs via a file or module global.
    Bypasses admission on purpose (same defense-in-depth rationale as
    test_sandbox_smoke.py's B-tier tests) -- even `import os` being
    G3-blocked at admission shouldn't be the ONLY reason this fails.

    Run 1's candidate writes a marker to /scratch. Run 2 is a SEPARATE
    `docker run` invocation (separate container, per launcher.py's
    --rm + fresh --tmpfs on every call) whose candidate checks whether
    that marker is still there. It must not be: --rm tears down the
    container's tmpfs when it exits, and the next `docker run` starts a
    brand new one.
    """
    write_memo = """\
from __future__ import annotations

# EVOLVE-BLOCK-START: circle_packing
def candidate_packing(n: int) -> list[tuple[float, float, float]]:
    with open("/scratch/memo.txt", "w") as f:
        f.write("i was here")
    return [(0.5, 0.5, 0.1)] * n
# EVOLVE-BLOCK-END: circle_packing
"""
    check_memo = """\
from __future__ import annotations
import os

# EVOLVE-BLOCK-START: circle_packing
def candidate_packing(n: int) -> list[tuple[float, float, float]]:
    found = os.path.exists("/scratch/memo.txt")
    # Report via radius rather than crashing either way, so the assertion
    # below does the judging instead of exception plumbing: 0.999 = "I
    # found stale state from a previous run", 0.1 = clean.
    r = 0.999 if found else 0.1
    return [(0.5, 0.5, r)] * n
# EVOLVE-BLOCK-END: circle_packing
"""
    work1 = _work_dir(tmp_path, write_memo, {"task": "circle_packing", "n": 1})
    env1 = run_in_sandbox(work1, seed=1, run_index=0)
    assert env1["runs"][0]["status"] == "ok"

    work2 = _work_dir(tmp_path, check_memo, {"task": "circle_packing", "n": 1})
    env2 = run_in_sandbox(work2, seed=2, run_index=0)
    assert env2["runs"][0]["status"] == "ok"
    reported_radius = env2["runs"][0]["outputs"]["circles"][0][2]
    assert reported_radius == 0.1, (
        "candidate found a marker file from a PREVIOUS container run -- "
        "state is leaking across --rm container boundaries"
    )


def test_c06_empty_output_after_early_exit_is_never_treated_as_valid(tmp_path):
    """C06: raise SystemExit(0) after producing nothing. The supervisor
    should observe exit code 0 (status='ok') but be unable to parse any
    outputs from empty stdout -- and envelope.py's host-side check must
    then refuse to treat that as a valid, scoreable result. This is the
    end-to-end version of tests/unit/test_envelope.py's
    test_none_outputs_is_attestation_failure, which only proves the host
    logic is correct in isolation; this proves the real supervisor+child
    path actually produces outputs=None for this exact attack.
    """
    candidate = """\
from __future__ import annotations
import sys

# EVOLVE-BLOCK-START: circle_packing
def candidate_packing(n: int) -> list[tuple[float, float, float]]:
    sys.exit(0)
# EVOLVE-BLOCK-END: circle_packing
"""
    work = _work_dir(tmp_path, candidate, {"task": "circle_packing", "n": 1})
    env = run_in_sandbox(work, seed=1, run_index=0)
    run = env["runs"][0]
    assert run["status"] == "ok"  # exit code 0 -- the process itself didn't crash
    assert run["outputs"] is None  # but nothing parseable was ever printed
    assert run["parse_status"].startswith("unparseable")

    from delta.evaluation.envelope import AttestationFailure, validate_outputs
    with pytest.raises(AttestationFailure):
        validate_outputs(run["outputs"])


def test_c10_oversized_payload_hits_the_byte_cap_not_the_scorer(tmp_path):
    """C10: emit an oversized payload to stall the host-side parser.
    600k tuples serializes to well over the supervisor's 8 MiB stdout cap
    (harness/supervisor.py's MAX_PAYLOAD) in well under a second and well
    under the container's 512m memory limit -- this deliberately does NOT
    also try to trigger a timeout or OOM kill at the same time, to isolate
    what's actually being tested: the byte cap catches it before json.loads
    (let alone the scorer) ever sees the payload.
    """
    candidate = """\
from __future__ import annotations

# EVOLVE-BLOCK-START: circle_packing
def candidate_packing(n: int) -> list[tuple[float, float, float]]:
    return [(0.123456789, 0.123456789, 0.123456789)] * 600_000
# EVOLVE-BLOCK-END: circle_packing
"""
    work = _work_dir(tmp_path, candidate, {"task": "circle_packing", "n": 1})
    env = run_in_sandbox(work, seed=1, run_index=0)
    run = env["runs"][0]
    assert run["status"] == "ok"  # the child process itself ran fine
    assert run["parse_status"] == "oversize"
    assert run["outputs"] is None  # never even attempted to parse it
    assert run["payload_bytes"] > 8 << 20
