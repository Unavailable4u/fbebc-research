# harness/supervisor.py
#
# Baked-into-nothing, actually: per the Phase1 guide's own launch command
# (§8.2), harness/ is bind-mounted read-only into the container, not COPY'd
# into an image. Stage 1 keeps this: it means Stage 1 needs no custom Docker
# image at all -- just a pinned upstream Python image (see
# delta/evaluation/launcher.py) plus this directory mounted `:ro`.
#
# This file is NEVER evolvable (Phase1 §4.1: "harness/ ... baked into the
# image, read-only mount"). It is the T2 process that forks and times the
# untrusted T3 candidate. Ported from Phase1 §8.3 with ONE deliberate cut:
# no latency is fed into fitness in Stage 1 (research-program-guide §1.1),
# so there is no timing cross-check here and no cpuset/BLAS-thread pinning
# in the launch command. wall_ns_supervisor is still recorded -- it is
# useful telemetry for spotting degenerate candidates (e.g. near-zero-time
# no-ops) even when it isn't a scored quantity -- but nothing downstream
# treats it as authoritative or uses it to compute fitness.
#
# Two independent timeouts are kept (host `timeout` around this whole
# process, FBEBC_TIMEOUT_S inside it): that's a hang-safety property, not a
# timing-fitness one, so Stage 1's scope cut doesn't touch it.

import json
import os
import resource
import signal
import subprocess
import sys
import time

TIMEOUT = float(os.environ["FBEBC_TIMEOUT_S"])
SEED = int(os.environ["FBEBC_SEED"])
RUN_INDEX = int(os.environ["FBEBC_RUN_INDEX"])
MAX_PAYLOAD = 8 << 20  # 8 MiB hard cap on candidate output (Phase1 §8.3 / C10)


def _rusage():
    r = resource.getrusage(resource.RUSAGE_CHILDREN)
    return r.ru_utime + r.ru_stime, r.ru_maxrss


def run_once(run_index: int) -> dict:
    cpu0, _ = _rusage()
    t0 = time.monotonic_ns()
    p = subprocess.Popen(
        [sys.executable, "-s", "-B", "/harness/child.py", "--seed", str(SEED)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd="/work",
        start_new_session=True,
    )
    try:
        out, err = p.communicate(timeout=TIMEOUT)
        status = "ok" if p.returncode == 0 else "nonzero_exit"
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass  # Phase1 §17 pitfall #6: already exited between check and kill.
        out, err = p.communicate()
        status = "timeout"
    wall_ns = time.monotonic_ns() - t0
    cpu1, peak_rss = _rusage()

    payload, parse_status = None, "none"
    if len(out) > MAX_PAYLOAD:
        parse_status = "oversize"  # ADV C10: 2GB-nested-JSON-style stall attempt
    else:
        try:
            payload = json.loads(out.decode("utf-8", "replace"))
            parse_status = "ok"
        except Exception as e:
            parse_status = f"unparseable:{type(e).__name__}"

    return {
        "run_index": run_index,
        "status": status,  # observed by the supervisor, never self-reported
        "exit_code": p.returncode,
        "wall_ns_supervisor": wall_ns,  # telemetry only -- not scored (Stage 1 cut)
        "cpu_s_supervisor": cpu1 - cpu0,
        "peak_rss_bytes": int(peak_rss) * 1024,
        "payload_bytes": len(out),
        "parse_status": parse_status,
        "outputs": payload,  # RAW OUTPUTS -- no score, ever (I3)
        "stderr_tail": err.decode("utf-8", "replace")[-4096:],
    }


if __name__ == "__main__":
    envelope = {
        "schema": "fbebc.result.v1",
        "seed": SEED,
        "runs": [run_once(RUN_INDEX)],
    }
    line = json.dumps(envelope, separators=(",", ":"))

    # Best-effort debug copy on the container's own tmpfs. This vanishes with
    # the container (--rm + tmpfs), so it is NOT the channel back to the host --
    # see the module docstring below for why stdout is.
    try:
        with open("/scratch/result.json", "w") as f:
            f.write(line)
    except OSError:
        pass

    # THE ACTUAL CHANNEL BACK TO THE HOST: stdout, and stdout alone.
    # The Phase1 guide's reference launch command doesn't specify how
    # /scratch/result.json crosses back out of an ephemeral, --read-only,
    # tmpfs-backed, --rm container -- there's no writable host-mounted volume
    # in that command, and there shouldn't be one (a writable mount back to
    # the host is exactly the kind of surface I1/I2 exist to avoid). Stage 1
    # closes that gap explicitly: the supervisor's only communication with
    # the host is one line of JSON on stdout, which `docker run` naturally
    # captures for us without adding any writable mount. Nothing the
    # candidate touches (it never sees stdout -- that's piped away into
    # `out` above) can inject anything else onto this stream.
    print(line, flush=True)
