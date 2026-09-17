# Build status

## Week 1 (research-program-guide §1.4) — DONE, tested, all 49 tests green

| Day | Planned | Status |
|---|---|---|
| 1-2 | Repo scaffold, `P_0` seed for both tasks, manifest builder (unchanged) | Done. `seed/binpacking/candidate.py`, `seed/circle_packing/candidate.py` (verbatim from the guide), `delta/integrity/manifest.py` (verbatim). |
| 3-5 | EVOLVE-BLOCK parser + bounded applicator (unchanged) + contract verification. Unit-test against hand-written diffs, no LLM. | Done. `blocks.py`, `applicator.py` verbatim; `contracts.py` ported with `PINNED` generalized to a per-task parameter (Stage 1 runs two tasks, the guide's version assumed one). 33 hand-written-diff tests across `test_blocks.py`, `test_applicator.py`, `test_contracts.py`, covering ADV-Tier-A-style attacks (boundary violation, marker injection, ambiguous match, contract violation) without needing the ADV harness yet. |
| 6-7 | Frozen AST edit-distance metric, frozen now before any mutation data exists. | Done, with one **disclosed deviation**: the guide calls an unspecified `_zhang_shasha_or_levenshtein` and says "supply your implementation." We supplied Levenshtein distance over the linearized canonical-AST node sequence, not true Zhang-Shasha tree edit distance. This is documented in `metrics.py`'s module docstring and must be stated in the paper's Methods/Limitations section per the guide's own honesty rules — it's a different, cheaper notion of tree distance that's a fine proxy for small single-block LLM diffs but can diverge for large subtree reorderings. |

Bonus, pulled forward from Phase 1's build order (§16, step 1.3, listed as parallelizable): `static_gate.py` (G3), unchanged, with its own "not a security boundary" caveat preserved.

## Week 2, Days 8-11 (research-program-guide §1.4) — built here, needs on-machine validation

Everything in this section was written and, where it doesn't require a real
Docker daemon, tested in the session that produced it (this container has no
`docker` binary — confirmed, not assumed). 86/86 tests green (49 from Week 1
+ 37 new).

| Day | Planned | Status |
|---|---|---|
| 8-9 | Docker sandbox: `harness/supervisor.py`, `harness/child.py`, launch command | Written. `harness/` adapted for **two** task signatures (`candidate_solver(instances, rng)` vs `candidate_packing(n)`) via a `task_input.json` dispatch, dropping the numpy dependency the Phase1 reference assumed (neither Stage 1 seed needs it). **No custom Dockerfile** — harness is bind-mounted `:ro` into a pinned upstream `python:3.12-slim`, same pattern as the Phase1 reference's own launch command. The supervisor↔host channel is a single stdout JSON line (the Phase1 guide doesn't specify how `/scratch/result.json` would otherwise escape an ephemeral `--rm` + tmpfs container — see `supervisor.py`'s docstring). Smoke-tested *outside* Docker (plain subprocess, no container) for both tasks and for timeout/crash/cheat paths — this exercises the process-split and JSON-envelope logic but **not** the actual kernel isolation (namespaces/cgroups/seccomp-equivalent), which only a real Docker daemon can provide. |
| 10-11 | Ledger (hash chain, `schema.sql`), wire G0-G3 + G5, record G4 | Written and fully unit-tested (pure Python + SQLite, no Docker needed). `delta/ledger/chain.py` + `schema.sql`: Stage-1-scoped column set (dropped everything timing/environment-fingerprint-only — see `schema.sql`'s docstring for the itemized list and why each is safe to cut). `delta/orchestrator.py`: `admit_candidate()` sequences G0→G5 in order, cheapest-first; G4 records `edit_metrics()` but doesn't enforce a threshold, exactly per this week's scope note. `delta/evaluation/envelope.py`: generic score-non-authorship + non-finite/rigged-numeric checks applied to *any* task's raw outputs before scoring (a disclosed simplification: **no timing cross-check** was ported, since Stage 1 has no latency in fitness to protect — see that file's docstring for the honesty-rule justification). `delta/control/channel.py`: ported unchanged from Phase1 §12, tested for halt/pause/resume semantics without relying on real OS signals. |

## Not yet built (Week 2 Day 12-14 onward)

- **Σ client against Gemini free tier + rejection-feedback loop** — Week 2 Day 12-14. Needs a real API key (yours, not mine) and network egress to `ai.google.dev` / `generativelanguage.googleapis.com`, which this container's egress allowlist doesn't include.
- **The generation loop itself** — nothing yet calls `admit_candidate()` → `evaluate()` in a cycle across generations, tracks the elite band, or feeds rejections back into the next Σ prompt. `evaluate.py`'s docstring is explicit that its caller (the loop) must halt on `IntegrityViolation`, not just skip one candidate.
- **The 8-10 case scoped ADV suite runs for real** — Week 3 Day 19-21. Tier A cases are effectively already exercised by the admission unit tests (hand-written diffs, no sandbox needed). Tier C (reward-hacking: direct score-key injection, NaN/rigged-float, oracle/instance-ID abuse) now has host-side defenses (`envelope.py`) but **has not been run against a real adversarial candidate inside a real container** — that requires your Docker daemon.
- **Elite-band vs single-winner ablation** — Week 4, tagged via the ledger's `ablation_config` column (already present in the schema, unused until then).

## Stage 1 exit checklist (research-program-guide §1.6) — progress

- [ ] `P_0` improves measurably over generations on circle packing — blocked on Σ client + generation loop
- [x] Manifest integrity mechanism built and unit-tested (full-run claim comes once real generations run)
- [ ] The 8-10 case adversarial suite passes — Tier A covered by unit tests; Tier C defenses written but not yet run against a live container
- [ ] Elite-band vs single-winner ablation — not started (Week 4)
- [x] Ledger chain built and unit-tested (hash chain, tamper detection, lineage/generation queries all verified)
- [ ] Sandbox hardening verified on a real Docker daemon — **not yet done; this is the next concrete step, see below**
- [ ] Repo clean enough to open-source — in progress
- [ ] Draft written per the paper guide — not started
- [ ] arXiv account / category — not started
