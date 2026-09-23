from pathlib import Path

import pytest

from delta.evaluation.launcher import build_docker_command


def test_hardening_flags_present():
    cmd = build_docker_command(Path("/tmp/work/c0"), seed=1, run_index=0,
                                image="python:3.12-slim", timeout_s=30)
    joined = " ".join(cmd)
    for flag in (
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--pids-limit=32",
        "--security-opt=no-new-privileges",
        "--ipc=none",
        "--cgroupns=private",
    ):
        assert flag in joined, f"missing hardening flag: {flag}"


def test_gvisor_and_timing_flags_absent():
    """Stage 1 scope cut (research-program-guide §1.1): no gVisor runtime,
    no cpuset pinning, no BLAS-thread env vars -- those exist only to
    support timing claims Stage 1 doesn't make."""
    cmd = build_docker_command(Path("/tmp/work/c0"), seed=1, run_index=0,
                                image="python:3.12-slim", timeout_s=30)
    joined = " ".join(cmd)
    for absent in ("runsc", "cpuset-cpus", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        assert absent not in joined


def test_seed_and_run_index_threaded_through():
    cmd = build_docker_command(Path("/tmp/work/c0"), seed=42, run_index=3,
                                image="python:3.12-slim", timeout_s=30)
    assert "FBEBC_SEED=42" in cmd
    assert "PYTHONHASHSEED=42" in cmd
    assert "FBEBC_RUN_INDEX=3" in cmd


def test_work_dir_mounted_read_only():
    cmd = build_docker_command(Path("/tmp/work/c0"), seed=1, run_index=0,
                                image="python:3.12-slim", timeout_s=30)
    assert any(a.endswith(":/work:ro") and "/tmp/work/c0" in a for a in cmd)


@pytest.mark.parametrize("host_env", [
    {"GROQ_API_KEY": "sk-fake-value-for-this-test-only"},
    {"OPENAI_API_KEY": "sk-fake-value-for-this-test-only"},
    {"UPSTASH_REDIS_REST_TOKEN": "fake-value-for-this-test-only"},
])
def test_no_env_flag_ever_names_a_secret_variable(monkeypatch, host_env):
    """ADV Tier B08 (tests/adv/COVERAGE.md's disclosed gap): the container
    must never receive a host secret, regardless of what's sitting in the
    host process's own os.environ when build_docker_command runs. This is
    a stronger, host-side version of that check -- it inspects the exact
    argv Docker would be invoked with, rather than only observing one
    candidate's view from inside one container on one machine. Only
    `-e NAME=value` pairs ever reach the container (no --env-file, no
    passthrough of the parent's environment), so asserting on the literal
    NAME=value strings is a complete check, not a sample of one.
    """
    for name, value in host_env.items():
        monkeypatch.setenv(name, value)
    cmd = build_docker_command(Path("/tmp/work/c0"), seed=1, run_index=0,
                                image="python:3.12-slim", timeout_s=30)
    e_flags = [cmd[i + 1] for i, a in enumerate(cmd) if a == "-e"]
    allowed = {"PYTHONHASHSEED", "PYTHONDONTWRITEBYTECODE", "FBEBC_SEED",
               "FBEBC_TIMEOUT_S", "FBEBC_RUN_INDEX"}
    for flag in e_flags:
        var_name = flag.split("=", 1)[0]
        assert var_name in allowed, f"unexpected -e flag reaches the container: {flag!r}"
    assert "--env-file" not in cmd
    joined = " ".join(cmd)
    for name, value in host_env.items():
        assert value not in joined, f"{name}'s value leaked into the docker command"


def test_two_independent_timeouts_present():
    """Host `timeout` wrapping the whole process, plus FBEBC_TIMEOUT_S
    inside it (Phase1 §8.2). This is a hang-safety property, not a
    timing-fitness one, so Stage 1 keeps both."""
    cmd = build_docker_command(Path("/tmp/work/c0"), seed=1, run_index=0,
                                image="python:3.12-slim", timeout_s=30)
    assert "FBEBC_TIMEOUT_S=30" in cmd
    assert "timeout" in cmd
