# delta/evaluation/launcher.py
#
# Host-side container launcher. Stage 1 scope (research-program-guide §1.1):
# "Docker with basic hardening (--network=none, --read-only, --cap-drop=ALL,
# --pids-limit)" -- explicitly NOT gVisor, NOT cpuset-pinned, NOT
# BLAS-thread-pinned. Those three exist in the Phase1 reference purely to
# support *timing* claims; Stage 1 makes none, so none of that machinery is
# built here. A few more zero-cost hardening flags are included beyond the
# four named in the cut table (--ipc=none, --cgroupns=private,
# --security-opt=no-new-privileges) because they cost nothing and don't
# reintroduce any of the complexity the cut table is protecting you from.
#
# No custom Docker image is built. harness/ is bind-mounted read-only into a
# pinned upstream python:3.12-slim, exactly as the Phase1 reference launch
# command does it (§8.2) -- see harness/supervisor.py's docstring.
#
# ENVIRONMENT NOTE: this needs a real Docker daemon with real Linux
# namespaces/cgroups underneath it (research-program-guide §1.3: "Linux or
# WSL2, not macOS/Windows Docker Desktop -- the VM layer breaks the
# isolation semantics you're testing"). If you're using Docker Desktop's
# WSL2 *integration* rather than a dockerd installed natively inside your
# WSL2 distro, check which one you actually have before trusting any ADV
# Tier B result -- see the chat guidance for how.

import json
import subprocess
from pathlib import Path

HARNESS_DIR = Path(__file__).resolve().parents[2] / "harness"

# TODO: run docker/pin_image.sh once on your machine and paste the result
# here. Pinning by digest, not tag, matters for reproducibility (Phase1
# guide §17, pitfall #5). Record whatever you end up with in your run
# manifest/README too.
PINNED_IMAGE = "python@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea"

DOCKER_TIMEOUT_OUTER_S = 45
FBEBC_TIMEOUT_INNER_S = 30


class SandboxError(RuntimeError):
    """The container itself failed to run or produce a parseable envelope --
    a Docker/host problem, distinct from a candidate producing a bad
    *result* inside a container that ran fine. Keeping these distinct
    matters when you're triaging a bad week-3 run at 2am."""


def build_docker_command(
    work_dir: Path, seed: int, run_index: int, *, image: str, timeout_s: int
) -> list[str]:
    """Pure function, no side effects -- kept separate from run_in_sandbox()
    so tests can assert on the exact flags without needing a Docker daemon."""
    return [
        "docker", "run", "--rm",
        "--network=none",
        "--ipc=none",
        "--cgroupns=private",
        "--read-only",
        "--user", "65534:65534",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--pids-limit=32",
        "--memory=512m", "--memory-swap=512m",
        "--cpus=1",
        "--ulimit", "nofile=128:128",
        "--ulimit", "fsize=33554432",
        "--ulimit", "core=0",
        "--tmpfs", "/scratch:rw,nosuid,nodev,size=64m,mode=0700",
        "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=32m",
        "-v", f"{HARNESS_DIR}:/harness:ro",
        "-v", f"{work_dir}:/work:ro",
        "-e", f"PYTHONHASHSEED={seed}",
        "-e", "PYTHONDONTWRITEBYTECODE=1",
        "-e", f"FBEBC_SEED={seed}",
        "-e", f"FBEBC_TIMEOUT_S={timeout_s}",
        "-e", f"FBEBC_RUN_INDEX={run_index}",
        image,
        "timeout", "--signal=KILL", str(DOCKER_TIMEOUT_OUTER_S),
        "python3", "-s", "-B", "/harness/supervisor.py",
    ]


def run_in_sandbox(
    work_dir: Path,
    seed: int,
    run_index: int,
    *,
    image: str = PINNED_IMAGE,
    timeout_s: int = FBEBC_TIMEOUT_INNER_S,
) -> dict:
    """Launch one candidate evaluation in a hardened, network-isolated
    container and return the parsed result envelope (Phase1 §9.2 schema).
    """
    cmd = build_docker_command(work_dir, seed, run_index, image=image, timeout_s=timeout_s)
    proc = subprocess.run(
        cmd, capture_output=True, text=True, timeout=DOCKER_TIMEOUT_OUTER_S + 10
    )
    if not proc.stdout.strip():
        raise SandboxError(
            f"container produced no stdout (exit {proc.returncode}): "
            f"{proc.stderr[-2000:]}"
        )
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as e:
        raise SandboxError(
            f"unparseable envelope from container: {e}\n"
            f"stdout={proc.stdout[-2000:]}\nstderr={proc.stderr[-2000:]}"
        )
