# harness/child.py
#
# Shares an address space with the candidate -- Phase1 §8.3's own honest
# framing applies verbatim: "anything it writes is untrusted by
# construction. That is fine, because it only writes *solutions*. Trust is
# reconstituted on the host, where the oracle lives." There is no oracle
# anywhere in this file or reachable from it.
#
# ONE ADAPTATION FROM THE PHASE1 REFERENCE: the guide's child.py is written
# for a single task with a fixed `candidate_solver(instances, rng)` shape and
# imports numpy for the injected RNG. Stage 1 runs two tasks with two
# different EVOLVE-BLOCK entry-point signatures (delta/admission/tasks.py):
#   - binpacking:      candidate_solver(instances: list[dict], rng) -> list[dict]
#   - circle_packing:  candidate_packing(n: int) -> list[tuple[float,float,float]]
# circle_packing's seed (research-program-guide §1.2, verbatim) takes no RNG
# at all, and neither seed needs numpy, so this version drops the numpy
# dependency entirely rather than carrying it for one task that doesn't use
# it -- a real simplification, disclosed here as such (it keeps the container
# image to plain `python:3.12-slim`, needing no custom build step).
#
# The RNG is still injected, not constructed, for the task that takes one
# (Phase1 §4.2's "host decision" rule) -- just `random.Random(seed)` instead
# of `numpy.random.default_rng(seed)`.

import argparse
import importlib.util
import json
import random
import sys

ap = argparse.ArgumentParser()
ap.add_argument("--seed", type=int, required=True)
args = ap.parse_args()

with open("/work/task_input.json") as f:  # host-generated, oracle-free
    task_input = json.load(f)
task = task_input["task"]

spec = importlib.util.spec_from_file_location("candidate", "/work/candidate.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)  # untrusted code begins executing here

if task == "binpacking":
    rng = random.Random(args.seed)  # injected, not chosen (Phase1 §4.2)
    results = mod.candidate_solver(task_input["instances"], rng)
    # allow_nan=False, ported from Phase1 §8.3: a candidate that returns
    # NaN/Inf fails HERE with a nonzero exit rather than reaching the host.
    # (ADV C05 covers rigged float subclasses too; those still serialize
    # normally through json and are caught host-side in envelope.py's
    # float() coercion -- see that file's docstring.)
    json.dump({"results": results}, sys.stdout, separators=(",", ":"), allow_nan=False)

elif task == "circle_packing":
    n = task_input["n"]
    circles = mod.candidate_packing(n)
    # JSON has no tuple type; host side (delta/evaluation/evaluate.py)
    # converts each [x, y, r] list back to a tuple before scoring.
    json.dump(
        {"circles": [list(c) for c in circles]},
        sys.stdout,
        separators=(",", ":"),
        allow_nan=False,
    )

else:
    raise ValueError(f"unknown task {task!r}")
