# delta/loop.py
#
# Week 2 Day 12-14: "debug until a full generation cycle runs clean"
# (research-program-guide §1.4). This is the piece nothing else in the repo
# builds on its own -- it's the actual per-generation cycle:
#   Sigma proposes a diff -> admit_candidate() (G0-G5) -> evaluate() (sandbox
#   + scoring + ledger) -> accept or keep the current parent -> repeat.
#
# Selection strategy: single-winner hill-climbing (Stage 1 default, per
# research-program-guide's Week 4 ablation framing -- "elite-band vs
# single-winner" implies single-winner IS this loop's baseline behavior,
# with the elite-band variant arriving later as the ablation's other arm).
# A child is only ever adopted as the next parent if it is attested, valid,
# and its fitness is >= the current parent's -- ties are kept (drift is
# free when it isn't worse) but never accepted on a decrease.
#
# The one hard rule this loop must respect, stated in evaluate.py's own
# docstring: STOP admitting new candidates the moment IntegrityViolation is
# raised. This loop does exactly that -- it does not catch that exception
# anywhere; it propagates to the caller (scripts/run_stage1.py), which is
# expected to halt the whole process, not just this loop.

import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .admission.errors import AdmissionError
from .admission.tasks import TaskSpec
from .control.channel import ControlChannel
from .evaluation.evaluate import evaluate as default_evaluate
from .integrity import manifest as manifest_mod
from .ledger.chain import Ledger
from .orchestrator import admit_candidate as default_admit_candidate
from .orchestrator import sanitize_rejection


@dataclass
class GenerationRecord:
    generation_index: int
    outcome: str  # "improved" | "kept" | "stalled"
    clone_id: str | None
    fitness: float | None


@dataclass
class RunSummary:
    task_name: str
    generations: list[GenerationRecord] = field(default_factory=list)
    best_fitness: float | None = None
    final_src: str = ""


def _record_rejection(
    ledger: Ledger, *, clone_id: str, parent_id: str | None, task_name: str,
    generation_index: int, p0_digest: str, seed: int, exc: AdmissionError,
    manifest_digest: str,
) -> None:
    """Rejections never reach evaluate.py (no sandbox run happens), so this
    loop is what logs them -- Phase1 §11: 'Log rejected candidates as well
    as admitted ones.'"""
    ledger.append({
        "clone_id": clone_id,
        "parent_id": parent_id,
        "task": task_name,
        "generation_index": generation_index,
        "p0_digest": p0_digest,
        "admitted": 0,
        "rejection_class": exc.code,
        "gate_failed": None,
        "candidate_digest": None,
        "semantic_fingerprint": None,
        "ast_distance_parent": None,
        "ast_distance_p0": None,
        "token_diff_parent": None,
        "nodes_added": None,
        "nodes_removed": None,
        "max_depth_delta": None,
        "seed": seed,
        "run_index": None,
        "status": None,
        "fitness": None,
        "manifest_pre": manifest_digest,
        "manifest_post": manifest_digest,
        "attested": 0,
        "image_digest": None,
        "python_version": None,
        "ablation_config": None,
        "stderr_tail": None,
    })


def run_generations(
    *,
    task: TaskSpec,
    n_generations: int,
    ledger: Ledger,
    work_root: Path,
    manifest_roots: list[Path],
    sigma,  # sigma.client.SigmaClient, or anything with .propose_diff(...)
    control: ControlChannel,
    seed_base: int = 0,
    max_retries_per_generation: int = 3,
    admit_fn=default_admit_candidate,
    evaluate_fn=default_evaluate,
) -> RunSummary:
    """Runs up to n_generations proposal/admit/evaluate cycles starting from
    task's own seed file. Raises manifest_mod.IntegrityViolation if it ever
    fires (see module docstring) -- the caller must not swallow that.
    """
    p0_src = manifest_mod.canonical_source(task.seed_path)
    p0_digest = manifest_mod.p0_digest(task.seed_path)
    expected_manifest = manifest_mod.build_manifest(manifest_roots)

    parent_src = p0_src
    parent_id: str | None = None
    best_fitness: float | None = None
    summary = RunSummary(task_name=task.name)

    for g in range(n_generations):
        control.checkpoint()  # drain point: raises SystemExit if halted

        prior_rejection = None
        admitted = None
        for _attempt in range(max_retries_per_generation):
            diff = sigma.propose_diff(task=task, parent_src=parent_src, prior_rejection=prior_rejection)
            clone_id = f"{task.name}-g{g}-{uuid.uuid4().hex[:8]}"
            try:
                admitted = admit_fn(
                    parent_src=parent_src, diff_text=diff, task=task, p0_src=p0_src,
                    expected_manifest=expected_manifest, manifest_roots=manifest_roots,
                )
                break
            except AdmissionError as e:
                _record_rejection(
                    ledger, clone_id=clone_id, parent_id=parent_id, task_name=task.name,
                    generation_index=g, p0_digest=p0_digest, seed=seed_base + g, exc=e,
                    manifest_digest=expected_manifest["root_digest"],
                )
                prior_rejection = sanitize_rejection(e)
                # IntegrityViolation is NOT caught here -- see module docstring.

        if admitted is None:
            summary.generations.append(
                GenerationRecord(generation_index=g, outcome="stalled", clone_id=None, fitness=None)
            )
            continue  # exhausted retries this generation; try again next generation

        result = evaluate_fn(
            candidate_src=admitted["child_src"], task_name=task.name, seed=seed_base + g,
            run_index=0, clone_id=clone_id, parent_id=parent_id, generation_index=g,
            p0_digest=p0_digest, admission_metrics=admitted["metrics"],
            manifest_expected=expected_manifest, manifest_roots=manifest_roots,
            work_root=work_root, ledger=ledger,
        )
        # IntegrityViolation from evaluate_fn also propagates uncaught.

        adopted = (
            result["attested"] and result["valid"]
            and (best_fitness is None or result["fitness"] >= best_fitness)
        )
        if adopted:
            parent_src = admitted["child_src"]
            parent_id = clone_id
            best_fitness = result["fitness"]
            outcome = "improved"
        else:
            outcome = "kept"

        summary.generations.append(
            GenerationRecord(generation_index=g, outcome=outcome, clone_id=clone_id, fitness=result["fitness"])
        )

    summary.best_fitness = best_fitness
    summary.final_src = parent_src
    return summary
