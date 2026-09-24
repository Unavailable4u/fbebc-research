# delta/loop.py
#
# Week 2 Day 12-14: "debug until a full generation cycle runs clean"
# (research-program-guide §1.4). This is the piece nothing else in the repo
# builds on its own -- it's the actual per-generation cycle:
#   Sigma proposes a diff -> admit_candidate() (G0-G5) -> evaluate() (sandbox
#   + scoring + ledger) -> accept or keep the current parent -> repeat.
#
# Selection strategy: delegated to delta/selection.py's EliteBand. band_size
# == 1 (the default) IS single-winner hill-climbing: a child becomes the
# next parent only if it is attested, valid, and its fitness is >= the
# incumbent's -- ties are adopted (drift is free when it isn't worse) but
# never accepted on a decrease. band_size > 1 is the Week 4 ablation's
# elite-band arm (top-k distinct candidates, parent sampled uniformly).
# One class, one parameter -- see selection.py for the pre-registered rule.
#
# Week 3 Day 16 additions (all default-off / backward compatible):
#   * evaluate_baseline: score P_0 itself in the sandbox before generation 0
#     (ledger generation_index = -1). Without it the FIRST admitted child is
#     adopted even if it scores BELOW the seed, and "did P_0 improve?" has no
#     measured denominator -- the guide's exit criterion (§1.6, first item).
#   * retry_exceptions: Sigma replies that were unusable (no hunk / empty
#     content) count as one wasted attempt, logged as E_NO_PROPOSAL, instead
#     of crashing an unattended multi-day run.
#   * ablation_config is written to every ledger record (selection label).
#
# The one hard rule this loop must respect, stated in evaluate.py's own
# docstring: STOP admitting new candidates the moment IntegrityViolation is
# raised. This loop does exactly that -- it does not catch that exception
# anywhere; it propagates to the caller (scripts/run_stage1.py), which is
# expected to halt the whole process, not just this loop.

import random
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from . import checkpoint as checkpoint_mod
from .admission.errors import AdmissionError
from .admission.metrics import edit_metrics, exact_fingerprint
from .admission.tasks import TaskSpec
from .control.channel import ControlChannel
from .evaluation.evaluate import evaluate as default_evaluate
from .integrity import manifest as manifest_mod
from .ledger.chain import Ledger
from .orchestrator import admit_candidate as default_admit_candidate
from .orchestrator import sanitize_rejection
from .selection import Elite, EliteBand, ablation_label


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
    stopped_reason: str | None = None  # e.g. "budget_exhausted"; None if
    # this invocation's requested n_generations was simply used up.
    baseline_fitness: float | None = None  # P_0's sandbox score, if evaluated this call
    stopped_detail: str | None = None  # str() of the stop exception, for diagnostics


def _record_rejection(
    ledger: Ledger, *, clone_id: str, parent_id: str | None, task_name: str,
    generation_index: int, p0_digest: str, seed: int, exc: AdmissionError,
    manifest_digest: str, ablation_config: str | None = None,
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
        "ablation_config": ablation_config,
        "stderr_tail": None,
    })


def _exact_fp_or_none(src: str) -> str | None:
    try:
        return exact_fingerprint(src)
    except SyntaxError:
        return None


def _normalize_band_fingerprints(band: EliteBand) -> EliteBand:
    """Members restored from a checkpoint written BEFORE exact_fingerprint
    existed carry the old node-type-only hash (no "x1:" prefix). Re-derive
    their key from the stored source so they compare correctly against new
    children; already-versioned keys are left alone."""
    fixed = []
    for e in band.elites:
        fp = e.fingerprint
        if not (isinstance(fp, str) and fp.startswith("x1:")):
            fp = _exact_fp_or_none(e.src)
        fixed.append(Elite(src=e.src, clone_id=e.clone_id, fitness=e.fitness, fingerprint=fp))
    return EliteBand(band.k, fixed)


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
    start_generation_index: int = 0,
    initial_parent_src: str | None = None,
    initial_parent_id: str | None = None,
    initial_best_fitness: float | None = None,
    checkpoint_path: Path | None = None,
    stop_exceptions: tuple[type[BaseException], ...] = (),
    retry_exceptions: tuple[type[BaseException], ...] = (),
    band_size: int = 1,
    initial_band: list[dict] | None = None,
    evaluate_baseline: bool = False,
) -> RunSummary:
    """Runs up to n_generations proposal/admit/evaluate cycles, resuming
    from (start_generation_index, initial_parent_src, initial_parent_id,
    initial_best_fitness) if given -- default (0, None, None, None) means
    "start fresh from task's own P_0 seed", same as before this parameter
    set existed. Raises manifest_mod.IntegrityViolation if it ever fires
    (see module docstring) -- the caller must not swallow that.

    stop_exceptions: exception types that, if raised by sigma.propose_diff,
    end the run cleanly (checkpoint saved, summary returned with
    stopped_reason set to the exception's class name) instead of
    propagating. This is how a Sigma-side daily-budget cap
    (sigma.budget.BudgetExceeded) turns into "come back tomorrow" rather
    than a crash -- deliberately plumbed as a caller-supplied predicate,
    not a hardcoded import of anything from the sigma package, so this
    module keeps knowing nothing about Sigma's internals (the Sigma-Delta
    structural separation this whole project is built around). Pass
    `(BudgetExceeded,)` from the call site that actually imports Sigma
    (scripts/run_stage1.py), not from here.

    checkpoint_path: if given, an up-to-date delta.checkpoint.RunCheckpoint
    is written after every generation (including the one that triggers a
    stop_exceptions stop) so the next invocation can resume exactly here.

    retry_exceptions: exception types from sigma.propose_diff meaning "the
    call worked but the reply was unusable" (sigma.client.SigmaProposalError).
    Each is logged as an E_NO_PROPOSAL rejection and retried with feedback,
    consuming one of max_retries_per_generation like any other rejection.
    Anything NOT listed here (network errors, bad key) still propagates.

    band_size / initial_band: selection state. band_size=1 is single-winner;
    >1 is the elite band. initial_band (a list of Elite dicts, order
    preserved) resumes a band from a checkpoint; if omitted, a legacy
    initial_parent_* triple is promoted to a one-member band. The parent for
    generation g is sampled with random.Random(f"{seed_base}:{g}"), so a
    resumed run picks exactly the parents an uninterrupted run would.

    evaluate_baseline: on a FRESH run only (no initial state, generation 0),
    score P_0 in the sandbox first and seed the band with it.
    """
    p0_src = manifest_mod.canonical_source(task.seed_path)
    p0_digest = manifest_mod.p0_digest(task.seed_path)
    expected_manifest = manifest_mod.build_manifest(manifest_roots)

    label = ablation_label(band_size)
    fallback_src = initial_parent_src if initial_parent_src is not None else p0_src
    fallback_id: str | None = initial_parent_id
    if initial_band is not None:
        band = _normalize_band_fingerprints(EliteBand.from_dicts(band_size, initial_band))
    elif initial_parent_src is not None and initial_best_fitness is not None:
        band = EliteBand(band_size, [Elite(
            src=initial_parent_src, clone_id=initial_parent_id, fitness=initial_best_fitness,
            fingerprint=_exact_fp_or_none(initial_parent_src),
        )])
    else:
        band = EliteBand(band_size)
    summary = RunSummary(task_name=task.name)

    def _save_checkpoint(next_gen: int) -> None:
        if checkpoint_path is None:
            return
        best = band.best()
        checkpoint_mod.save(
            checkpoint_path,
            checkpoint_mod.RunCheckpoint(
                task_name=task.name, seed_base=seed_base, next_generation_index=next_gen,
                parent_src=best.src if best else fallback_src,
                parent_id=best.clone_id if best else fallback_id,
                best_fitness=best.fitness if best else None,
                band_size=band_size, band=band.to_dicts(),
            ),
        )

    if (
        evaluate_baseline and initial_band is None and initial_parent_src is None
        and start_generation_index == 0
    ):
        control.checkpoint()
        base_id = f"{task.name}-p0-{uuid.uuid4().hex[:8]}"
        p0_metrics = edit_metrics(p0_src, p0_src, p0_src)
        base = evaluate_fn(
            candidate_src=p0_src, task_name=task.name, seed=seed_base, run_index=0,
            clone_id=base_id, parent_id=None, generation_index=-1, p0_digest=p0_digest,
            admission_metrics=p0_metrics, manifest_expected=expected_manifest,
            manifest_roots=manifest_roots, work_root=work_root, ledger=ledger,
            ablation_config=label,
        )
        if not (base["attested"] and base["valid"]):
            raise RuntimeError(
                f"P_0 baseline evaluation was not attested+valid ({base!r}) -- the seed "
                f"itself does not score, so no generation result would be interpretable."
            )
        band.consider(Elite(
            src=p0_src, clone_id=base_id, fitness=base["fitness"],
            fingerprint=p0_metrics["exact_fingerprint"],
        ))
        summary.baseline_fitness = base["fitness"]
        _save_checkpoint(next_gen=start_generation_index)

    for g in range(start_generation_index, start_generation_index + n_generations):
        control.checkpoint()  # drain point: raises SystemExit if halted

        # Parent for this generation: fixed BEFORE the retry loop so every
        # retry within a generation proposes against the same parent.
        picked = band.pick_parent(random.Random(f"{seed_base}:{g}"))
        parent_src = picked.src if picked else fallback_src
        parent_id = picked.clone_id if picked else fallback_id

        prior_rejection = None
        admitted = None
        stopped_by = None
        for _attempt in range(max_retries_per_generation):
            clone_id = f"{task.name}-g{g}-{uuid.uuid4().hex[:8]}"
            try:
                diff = sigma.propose_diff(task=task, parent_src=parent_src, prior_rejection=prior_rejection)
            except stop_exceptions as e:
                stopped_by = e
                break
            except retry_exceptions as e:
                exc = AdmissionError("E_NO_PROPOSAL", str(e)[:300])
                _record_rejection(
                    ledger, clone_id=clone_id, parent_id=parent_id, task_name=task.name,
                    generation_index=g, p0_digest=p0_digest, seed=seed_base + g, exc=exc,
                    manifest_digest=expected_manifest["root_digest"], ablation_config=label,
                )
                prior_rejection = {
                    "code": "E_NO_PROPOSAL",
                    "message": "Your previous reply contained no usable SEARCH/REPLACE block. "
                               "Reply with exactly one, in the required format.",
                }
                continue
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
                    manifest_digest=expected_manifest["root_digest"], ablation_config=label,
                )
                prior_rejection = sanitize_rejection(e)
                # IntegrityViolation is NOT caught here -- see module docstring.

        if stopped_by is not None:
            # Nothing happened for generation g -- no Sigma call succeeded,
            # so no diff/admission/evaluation exists to log. Next resume
            # retries g from scratch, against unchanged parent state.
            _save_checkpoint(next_gen=g)
            summary.stopped_reason = type(stopped_by).__name__
            summary.stopped_detail = str(stopped_by)
            break

        if admitted is None:
            summary.generations.append(
                GenerationRecord(generation_index=g, outcome="stalled", clone_id=None, fitness=None)
            )
            _save_checkpoint(next_gen=g + 1)
            continue  # exhausted retries this generation; try again next generation

        result = evaluate_fn(
            candidate_src=admitted["child_src"], task_name=task.name, seed=seed_base + g,
            run_index=0, clone_id=clone_id, parent_id=parent_id, generation_index=g,
            p0_digest=p0_digest, admission_metrics=admitted["metrics"],
            manifest_expected=expected_manifest, manifest_roots=manifest_roots,
            work_root=work_root, ledger=ledger, ablation_config=label,
        )
        # IntegrityViolation from evaluate_fn also propagates uncaught.

        # "improved" == entered the band (for band_size=1: became the new
        # incumbent). Unattested / invalid candidates never enter selection.
        entered = (
            result["attested"] and result["valid"]
            and band.consider(Elite(
                src=admitted["child_src"], clone_id=clone_id, fitness=result["fitness"],
                fingerprint=admitted["metrics"].get("exact_fingerprint"),
            ))
        )
        outcome = "improved" if entered else "kept"

        summary.generations.append(
            GenerationRecord(generation_index=g, outcome=outcome, clone_id=clone_id, fitness=result["fitness"])
        )
        _save_checkpoint(next_gen=g + 1)

    best = band.best()
    summary.best_fitness = best.fitness if best else None
    summary.final_src = best.src if best else fallback_src
    return summary
