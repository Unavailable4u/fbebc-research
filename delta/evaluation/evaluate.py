# delta/evaluation/evaluate.py
#
# The Stage-1-scoped `evaluate()` from the Phase1 §14 frozen interface.
# Dropped fields vs. the guide's AttestedResult, all for the same reason
# (research-program-guide §1.1, correctness-only fitness): latency_ns,
# timing_anomaly. `env_fingerprint` is reduced to the two fields that still
# matter without a timing claim (image_digest, python_version) -- see
# delta/ledger/schema.sql's docstring for the full list of what's dropped
# and why.
#
# This function does the full per-candidate cycle: pre-manifest check,
# write the candidate + task input into a per-clone work directory, launch
# the sandbox, attest + score the result, post-manifest check, ledger
# append. It does NOT do admission (G0-G4) -- call orchestrator.admit_candidate()
# first and only pass its output here. Keeping these separate mirrors the
# Phase1 layout (admission/ vs evaluation/ are different trust operations)
# and means a rejected candidate never touches Docker at all.

import json
import platform
from pathlib import Path

from . import envelope as envelope_mod
from .launcher import PINNED_IMAGE, SandboxError, run_in_sandbox
from .scorer_binpacking import make_fixed_instance_set, score_binpacking
from .scorer_circle_packing import score_packing
from ..ledger.chain import Ledger


def _task_input(task_name: str, seed: int) -> dict:
    if task_name == "binpacking":
        return {"task": "binpacking", "instances": make_fixed_instance_set(seed=seed)}
    if task_name == "circle_packing":
        # n=26, matching research-program-guide §1.2's AlphaEvolve reference
        # point. Override at the call site for smoke tests with a smaller n.
        return {"task": "circle_packing", "n": 26}
    raise KeyError(f"unknown task {task_name!r}")


def _score(task_name: str, task_input: dict, outputs: dict) -> dict:
    if task_name == "binpacking":
        instances = task_input["instances"]
        results = outputs.get("results")
        if not isinstance(results, list) or len(results) != len(instances):
            return {"fitness": None, "valid": False, "reason": "wrong_count"}
        by_id = {i["instance_id"]: i for i in instances}
        seen: set[str] = set()
        total_bins = 0
        for r in results:
            iid = r.get("instance_id") if isinstance(r, dict) else None
            if iid not in by_id or iid in seen:
                return {"fitness": None, "valid": False, "reason": "unknown_or_duplicate_instance"}
            seen.add(iid)
            res = score_binpacking(by_id[iid], r.get("solution"))
            if not res["valid"]:
                return {"fitness": None, "valid": False, "reason": res["reason"]}
            total_bins += res["bins_used"]
        return {"fitness": -float(total_bins), "valid": True}

    if task_name == "circle_packing":
        n = task_input["n"]
        circles_raw = outputs.get("circles")
        if not isinstance(circles_raw, list):
            return {"fitness": 0.0, "valid": False, "reason": "malformed_output"}
        try:
            circles = [tuple(float(v) for v in c) for c in circles_raw]
        except (TypeError, ValueError):
            return {"fitness": 0.0, "valid": False, "reason": "non_numeric_output"}
        return score_packing(circles, n)

    raise KeyError(task_name)


def evaluate(
    *,
    candidate_src: str,
    task_name: str,
    seed: int,
    run_index: int,
    clone_id: str,
    parent_id: str | None,
    generation_index: int,
    p0_digest: str,
    admission_metrics: dict,
    manifest_expected: dict,
    manifest_roots: list[Path],
    work_root: Path,
    ledger: Ledger,
    ablation_config: str | None = None,
) -> dict:
    """Evaluate one already-*admitted* candidate. Always appends a ledger
    record, admitted or not scoreable, per Phase1 §11: "Log rejected
    candidates as well as admitted ones."

    Returns {"fitness": float|None, "valid": bool, "status": str, "attested": bool}.
    `attested=False` candidates MUST NOT enter selection (Phase1 §14, hard rule 1).
    """
    from ..integrity import manifest as manifest_mod

    manifest_pre = manifest_mod.verify(manifest_expected, manifest_roots)["root_digest"]

    work_dir = work_root / clone_id
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "candidate.py").write_text(candidate_src, encoding="utf-8")
    task_input = _task_input(task_name, seed)
    (work_dir / "task_input.json").write_text(json.dumps(task_input), encoding="utf-8")

    status, fitness, valid, scored_ok = "sandbox_error", None, False, False
    rejection_class = None
    try:
        env = run_in_sandbox(work_dir, seed, run_index)
        run = env["runs"][0]
        status = run["status"]
        if status == "ok":
            try:
                envelope_mod.validate_outputs(run.get("outputs"))
                result = _score(task_name, task_input, run["outputs"])
                fitness, valid = result["fitness"], result["valid"]
                scored_ok = True
            except envelope_mod.SchemaViolation:
                rejection_class = "E_SCHEMA_VIOLATION"
            except envelope_mod.AttestationFailure:
                rejection_class = "E_ATTESTATION_FAILURE"
        # status in {"timeout", "nonzero_exit"}: ordinary execution failure
        # (Appendix B: S_TIMEOUT / S_NONZERO_EXIT) -- fitness stays None,
        # this is explicitly NOT a barrier violation.
    except SandboxError:
        status = "sandbox_error"

    manifest_post = manifest_mod.build_manifest(manifest_roots)["root_digest"]
    integrity_ok = manifest_pre == manifest_post
    attested = scored_ok and integrity_ok

    record = {
        "clone_id": clone_id,
        "parent_id": parent_id,
        "task": task_name,
        "generation_index": generation_index,
        "p0_digest": p0_digest,
        "admitted": 1,
        "rejection_class": rejection_class,
        "gate_failed": "post" if rejection_class else None,
        "candidate_digest": admission_metrics.get("semantic_fingerprint"),
        "semantic_fingerprint": admission_metrics.get("semantic_fingerprint"),
        "ast_distance_parent": admission_metrics.get("ast_distance_parent"),
        "ast_distance_p0": admission_metrics.get("ast_distance_p0"),
        "token_diff_parent": admission_metrics.get("token_diff_parent"),
        "nodes_added": admission_metrics.get("nodes_added"),
        "nodes_removed": admission_metrics.get("nodes_removed"),
        "max_depth_delta": admission_metrics.get("max_depth_delta"),
        "seed": seed,
        "run_index": run_index,
        "status": status,
        "fitness": fitness,
        "manifest_pre": manifest_pre,
        "manifest_post": manifest_post,
        "attested": int(attested),
        "image_digest": PINNED_IMAGE,
        "python_version": platform.python_version(),
        "ablation_config": ablation_config,
        "stderr_tail": None,
    }
    ledger.append(record)

    if not integrity_ok:
        # I1 violated. This is the one thing Phase1 exists to prevent
        # (Phase1 §5): "halt the run immediately ... mark the current
        # generation and all descendants UNATTESTED." The ledger record
        # above already carries attested=0; the CALLER (your generation
        # loop, Week 2 Day 12-14) must stop admitting new candidates on
        # seeing this exception, not just skip this one candidate.
        raise manifest_mod.IntegrityViolation(
            f"manifest changed during evaluation of {clone_id}: "
            f"pre={manifest_pre} post={manifest_post}"
        )

    return {"fitness": fitness, "valid": valid, "status": status, "attested": bool(attested)}
