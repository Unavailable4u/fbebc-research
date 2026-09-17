from pathlib import Path

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


def test_two_independent_timeouts_present():
    """Host `timeout` wrapping the whole process, plus FBEBC_TIMEOUT_S
    inside it (Phase1 §8.2). This is a hang-safety property, not a
    timing-fitness one, so Stage 1 keeps both."""
    cmd = build_docker_command(Path("/tmp/work/c0"), seed=1, run_index=0,
                                image="python:3.12-slim", timeout_s=30)
    assert "FBEBC_TIMEOUT_S=30" in cmd
    assert "timeout" in cmd
