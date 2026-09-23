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

## Sandbox hardening — VERIFIED on real hardware (2026-09-17)

Confirmed on a native Docker Engine 29.8.1 install inside WSL2 Ubuntu
(`docker context ls` → `default`, not Docker Desktop's `desktop-linux`
integration — see WEEK2_SETUP.md for why that distinction matters and how
to check it yourself). All 6 `tests/integration/test_sandbox_smoke.py`
cases passed: basic roundtrip, network isolation (`--network=none`),
read-only root filesystem, PID-limit containment of a fork bomb,
memory-limit containment of a memory bomb, and the host-side
score-smuggling defense. Image pinned by digest:
`python@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea`.

This is the first result in the project citable in the paper's Methods
section without a caveat about the test environment.

## Week 2, Day 12-14 — Σ client + generation loop, built and unit-tested
"native Docker Engine on WSL2 Ubuntu, kernel 6.18.33.2-microsoft-standard-WSL2"
**Disclosed substitution:** the research-program-guide pins Gemini 2.5
Flash-Lite for Σ; this build uses **Groq's `openai/gpt-oss-120b`
(free tier)** instead — same spirit as the guide's own "verify current
limits before you start, these move" caveat on that pin, and a real
example of exactly that: the initial choice, `llama-3.3-70b-versatile`,
was confirmed retired from Groq's catalog via a live `404 model_not_found`
on 2026-09-17, so this ended up on the fallback model identified when the
provider was first chosen. State whichever provider/model you actually ran
with in the paper's Methods section. `gpt-oss-120b`'s free-tier limits per
Groq's own docs (2026-09-17): 30 RPM / 1K RPD / 8K TPM / 200K TPD —
comfortably covers this pipeline's small per-call token counts.

**Also confirmed live:** Cloudflare fronts `api.groq.com` and blocks
plain `urllib`'s default `Python-urllib/3.x` User-Agent as a bot signature
(`403`, `error code: 1010`) before the request ever reaches Groq's own
auth layer — a known, widely-reported issue affecting any bare-urllib
client, nothing account-specific. Fixed with an explicit `User-Agent`
header in `sigma/client.py`; there's a regression test for it in
`tests/unit/test_sigma_client.py`.

- `sigma/prompts.py` — system prompt (cooperative, NOT the Tier-C
  adversarial "maximize score by any means" prompt, which is a separate,
  clearly-labeled future artifact for Week 3's red-teaming) + per-task
  objective descriptions + rejection-feedback formatting.
- `sigma/budget.py` — local daily request counter, checked *before* every
  network call, so an exhausted budget fails fast and locally instead of
  as a 429 mid-run.
- `sigma/client.py` — plain REST against Groq's OpenAI-compatible
  endpoint, no SDK dependency. **Not exercised against the live API from
  the session that wrote it** (no network egress to `api.groq.com` there)
  — run `python -m sigma.client` once, for real, before trusting it in a
  full loop.
- `delta/orchestrator.py` — added `sanitize_rejection()`: renders an
  `AdmissionError` as Σ-facing feedback text, never gate internals (Phase1
  §6's rule).
- `delta/loop.py` — `run_generations()`: the actual per-generation cycle
  (propose → admit → evaluate → adopt-if-not-worse → repeat). Single-winner
  hill-climbing is Stage 1's default selection strategy — the Week 4
  ablation's "elite-band" arm is a variant on top of this, not a rewrite of
  it. Fully unit-tested with a scripted fake Σ and faked admit/evaluate
  functions (22 new tests total across budget/client/loop), covering:
  improved vs. kept vs. stalled outcomes, rejection logging + feedback
  threading, a pre-halted control channel stopping before any generation
  runs, and `IntegrityViolation` propagating uncaught rather than being
  swallowed.
- `scripts/run_stage1.py` — CLI entrypoint. **Not yet run for real** (needs
  your `GROQ_API_KEY` and the Docker daemon together in one place) — this
  is the next concrete step.

108/108 tests green (86 from before + 22 new).

## Not yet built (Week 3 onward)

- **A real end-to-end generation run** — `scripts/run_stage1.py --task
  binpacking --generations 5` has not actually been executed yet. Do this
  before anything else; it's the thing that turns all of the above from
  "unit-tested" into "actually works."
- **The 8-10 case scoped ADV suite, Tier C, run for real** — Week 3 Day
  19-21. Tier A is covered by admission unit tests. Tier C
  (reward-hacking) has host-side defenses (`envelope.py`, verified against
  a live container for the score-smuggling case specifically) but the
  full scoped suite hasn't been run end to end yet.
- **Switch to circle_packing for the reported results** — Week 3.
  Binpacking is pipeline-debugging only.
- **Elite-band vs single-winner ablation** — Week 4, tagged via the
  ledger's `ablation_config` column (present in the schema, unused until
  then).

## Stage 1 exit checklist (research-program-guide §1.6) — progress

- [ ] `P_0` improves measurably over generations on circle packing — blocked on a real run (see above)
- [x] Manifest integrity mechanism built and unit-tested (full-run claim comes once real generations run)
- [ ] The 8-10 case adversarial suite passes — Tier A covered by unit tests; Tier C defenses written and partially live-verified, full suite not yet run end to end
- [ ] Elite-band vs single-winner ablation — not started (Week 4)
- [x] Ledger chain built and unit-tested (hash chain, tamper detection, lineage/generation queries all verified)
- [x] Sandbox hardening verified on a real Docker daemon
- [ ] Repo clean enough to open-source — in progress
- [ ] Draft written per the paper guide — not started
- [ ] arXiv account / category — not started
