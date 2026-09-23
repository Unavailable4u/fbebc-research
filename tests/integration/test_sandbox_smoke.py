# tests/integration/test_sandbox_smoke.py
#
# These tests need a REAL Docker daemon with real Linux namespaces/cgroups
# underneath it. They will NOT run in the chat sandbox that helped write
# this code (no `docker` binary there). Run them explicitly on your WSL2
# box:
#
#   pytest tests/integration -v
#
# pytest.ini scopes the default `pytest` run to tests/unit only, so these
# never run by accident. A couple of these deliberately try to misbehave
# (fork bomb, memory bomb) to confirm the *container's own* cgroup limits
# catch it -- that's the point of ADV Tier B. They should be safe on a
# correctly configured Docker daemon (the limits are enforced on the
# container's own cgroup), but if you're at all unsure about your setup,
# read research-program-guide §1.3 and the chat's WSL2/Docker-Desktop note
# before running this file for the first time.

import json
import shutil

import pytest

from delta.evaluation.launcher import SandboxError, run_in_sandbox

pytestmark = pytest.mark.skipif(
    shutil.which("docker") is None, reason="requires a real Docker daemon"
)


def _work_dir(tmp_path, candidate_src: str, task_input: dict):
    d = tmp_path / "work"
    d.mkdir()
    (d / "candidate.py").write_text(candidate_src, encoding="utf-8")
    (d / "task_input.json").write_text(json.dumps(task_input), encoding="utf-8")
    return d


CIRCLE_SEED = """\
from __future__ import annotations
import math

# EVOLVE-BLOCK-START: circle_packing
def candidate_packing(n: int) -> list[tuple[float, float, float]]:
    side = math.ceil(math.sqrt(n))
    r = 1.0 / (2 * side)
    out = []
    for i in range(n):
        x = (i % side + 0.5) * (1.0 / side)
        y = (i // side + 0.5) * (1.0 / side)
        out.append((x, y, r))
    return out
# EVOLVE-BLOCK-END: circle_packing
"""


def test_basic_roundtrip(tmp_path):
    """If this fails, nothing else in this file is worth debugging yet --
    start here."""
    work = _work_dir(tmp_path, CIRCLE_SEED, {"task": "circle_packing", "n": 8})
    env = run_in_sandbox(work, seed=1, run_index=0)
    run = env["runs"][0]
    assert run["status"] == "ok"
    assert len(run["outputs"]["circles"]) == 8


def test_network_is_actually_isolated(tmp_path):
    """B-tier: bypasses admission on purpose (this calls run_in_sandbox
    directly, not admit_candidate) to test the KERNEL boundary, not the
    AST-level G3 filter that would normally catch `import socket` earlier.
    Defense in depth means this must fail even if G3 didn't exist."""
    candidate = """\
from __future__ import annotations
import socket

# EVOLVE-BLOCK-START: circle_packing
def candidate_packing(n: int) -> list[tuple[float, float, float]]:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(3)
    s.connect(("8.8.8.8", 53))  # should never succeed with --network=none
    return [(0.5, 0.5, 0.1)] * n
# EVOLVE-BLOCK-END: circle_packing
"""
    work = _work_dir(tmp_path, candidate, {"task": "circle_packing", "n": 1})
    env = run_in_sandbox(work, seed=1, run_index=0)
    run = env["runs"][0]
    assert run["status"] == "nonzero_exit"
    assert "socket" in run["stderr_tail"].lower() or "network" in run["stderr_tail"].lower()


def test_filesystem_is_actually_read_only(tmp_path):
    """B-tier: confirms --read-only is real, independent of anything Python
    itself would have stopped candidate.py from doing."""
    candidate = """\
from __future__ import annotations

# EVOLVE-BLOCK-START: circle_packing
def candidate_packing(n: int) -> list[tuple[float, float, float]]:
    with open("/harness/supervisor.py", "w") as f:
        f.write("tampered")
    return [(0.5, 0.5, 0.1)] * n
# EVOLVE-BLOCK-END: circle_packing
"""
    work = _work_dir(tmp_path, candidate, {"task": "circle_packing", "n": 1})
    env = run_in_sandbox(work, seed=1, run_index=0)
    run = env["runs"][0]
    assert run["status"] == "nonzero_exit"


def test_pids_limit_contains_fork_bomb(tmp_path):
    """B-tier, deliberately adversarial. --pids-limit=32 should make this
    fail fast (OSError: Resource temporarily unavailable) rather than
    consuming host resources. Enforcement happens on the container's own
    cgroup, not the host's."""
    candidate = """\
from __future__ import annotations
import os

# EVOLVE-BLOCK-START: circle_packing
def candidate_packing(n: int) -> list[tuple[float, float, float]]:
    pids = []
    try:
        for _ in range(1000):
            pids.append(os.fork())
    except OSError:
        pass
    return [(0.5, 0.5, 0.1)] * n
# EVOLVE-BLOCK-END: circle_packing
"""
    work = _work_dir(tmp_path, candidate, {"task": "circle_packing", "n": 1})
    env = run_in_sandbox(work, seed=1, run_index=0, timeout_s=15)
    run = env["runs"][0]
    # Either it degrades gracefully (status ok, pids capped) or the
    # container gets killed for exceeding its limits -- either is
    # acceptable as long as the HOST never sees 1000 new processes. What's
    # NOT acceptable is a hang past the timeout.
    assert run["status"] in ("ok", "nonzero_exit", "timeout")


def test_memory_limit_contains_bomb(tmp_path):
    """B-tier, deliberately adversarial. --memory=512m should trigger an
    OOM kill well before the host notices."""
    candidate = """\
from __future__ import annotations

# EVOLVE-BLOCK-START: circle_packing
def candidate_packing(n: int) -> list[tuple[float, float, float]]:
    hog = []
    while True:
        hog.append(bytearray(64 * 1024 * 1024))  # 64 MiB per iteration
# EVOLVE-BLOCK-END: circle_packing
"""
    work = _work_dir(tmp_path, candidate, {"task": "circle_packing", "n": 1})
    env = run_in_sandbox(work, seed=1, run_index=0, timeout_s=15)
    run = env["runs"][0]
    assert run["status"] in ("nonzero_exit", "timeout")


def test_no_host_secrets_reachable_inside_container(tmp_path, monkeypatch):
    """B08 (tests/adv/COVERAGE.md's disclosed gap, now closed): a candidate
    running inside the container enumerates its own os.environ and fails
    itself if anything secret-shaped is visible. The host process (this
    test) has a fake secret sitting in os.environ the whole time -- if
    launcher.py ever changed to pass the parent environment through
    (--env-file, or forwarding os.environ into subprocess.run without
    clearing it), this is the test that would catch it. Complements
    test_launcher.py's host-side, no-Docker version of the same claim,
    which checks the exact argv Docker is invoked with rather than
    observing it empirically from inside a live container.
    """
    monkeypatch.setenv("GROQ_API_KEY", "sk-fake-test-value-should-never-cross-the-boundary")
    monkeypatch.setenv("UPSTASH_REDIS_REST_TOKEN", "fake-test-value-should-never-cross-the-boundary")
    candidate = """\
from __future__ import annotations
import os

# EVOLVE-BLOCK-START: circle_packing
def candidate_packing(n: int) -> list[tuple[float, float, float]]:
    suspicious = [k for k in os.environ if "GROQ" in k.upper() or "API_KEY" in k.upper()
                  or "TOKEN" in k.upper() or "SECRET" in k.upper()]
    if suspicious:
        raise RuntimeError(f"host secret reachable inside container: {suspicious}")
    return [(0.5, 0.5, 0.1)] * n
# EVOLVE-BLOCK-END: circle_packing
"""
    work = _work_dir(tmp_path, candidate, {"task": "circle_packing", "n": 1})
    env = run_in_sandbox(work, seed=1, run_index=0)
    run = env["runs"][0]
    assert run["status"] == "ok"


def test_score_smuggling_rejected_by_host(tmp_path):
    """C-tier: a candidate that runs fine inside the container but tries to
    author its own score. The container has no opinion about this -- the
    defense is entirely host-side (delta/evaluation/envelope.py)."""
    from delta.evaluation.envelope import SchemaViolation

    candidate = """\
from __future__ import annotations

# EVOLVE-BLOCK-START: circle_packing
def candidate_packing(n: int) -> list[tuple[float, float, float]]:
    return [(0.5, 0.5, 0.1)] * n
# EVOLVE-BLOCK-END: circle_packing
"""
    work = _work_dir(tmp_path, candidate, {"task": "circle_packing", "n": 1})
    env = run_in_sandbox(work, seed=1, run_index=0)
    run = env["runs"][0]
    assert run["status"] == "ok"  # the container is happy; the host is not

    from delta.evaluation import envelope as envelope_mod

    # Simulate what a candidate WOULD have to do to inject a score key --
    # the real attack surface is the outputs dict itself, so we assert the
    # validator rejects it regardless of how it got there.
    hacked_outputs = dict(run["outputs"])
    hacked_outputs["score"] = 999.0
    with pytest.raises(SchemaViolation):
        envelope_mod.validate_outputs(hacked_outputs)
