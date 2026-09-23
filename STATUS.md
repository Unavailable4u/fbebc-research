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

## Week 3, Day 15 — `/scratch` permission bug found and fixed via new ADV cases, first real end-to-end run (2026-09-23)

**Image re-pinned again:** `PINNED_IMAGE` is now
`python@sha256:2f17fc044b579bab302c2e8054d3a686e2cb9a83de48e70534b94cd8ebbe06a9`,
superseding the 2026-09-17 digest recorded above. Record whichever digest
is live at the time you generate the paper's reported results — don't
assume the two entries in this file mean the same image was used
throughout.

**New ADV cases added** (`tests/adv/test_tier_a_boundary.py` — A07;
`tests/adv/test_tier_c_reward_hacking.py` — C09;
`tests/integration/test_adv_tier_c_runtime.py` — C04, C06, C10), bringing
the scoped suite to 13/17 Tier A+C cases directly tested (exceeds the
8–10 target; see `tests/adv/COVERAGE.md` for the full tally and the 4
disclosed-N/A cases: C01, C03, C07, C08). 116/116 unit+adv tests green
immediately, no Docker needed for those.

**Real bug found by the new suite, not flakiness:** `test_c04` failed on
first run with the child process exiting nonzero. Root cause: the
`/scratch` tmpfs was mounted `mode=0700` with no `uid`/`gid`, so it was
owned by root, while the container runs `--user 65534:65534` — that user
had zero permissions on it. Any candidate touching `/scratch` (including
`supervisor.py`'s own best-effort debug copy of the result envelope,
silently swallowed by its `except OSError`) had been failing unnoticed
since the 2026-09-17 hardening verification; no test before C04 ever
exercised a candidate actually writing there. Fixed in
`delta/evaluation/launcher.py` by adding `uid=65534,gid=65534` to the
tmpfs mount options, keeping `mode=0700` so `/scratch` stays private to
the container's own user rather than becoming world-writable like
`/tmp`. `tests/unit/test_launcher.py` doesn't assert on the exact tmpfs
string, so nothing there needed updating.

A second, unrelated bug surfaced once the first was fixed: the ADV
patch's `_work_dir()` test helper always names its directory `work`
under `tmp_path`; `test_c04` calls it twice with the same `tmp_path` (one
directory per container run), so the second call's `mkdir()` collided
with the first (`FileExistsError`). Fixed by giving `_work_dir()` an
optional `name` parameter (default unchanged, so `test_c06`/`test_c10`'s
single calls are unaffected) and passing `name="work1"`/`name="work2"`
at `test_c04`'s two call sites.

With both fixed: **9/9 integration tests pass**, including C04 now
proving what it's actually meant to — that `--rm` plus a fresh `--tmpfs`
prevents state from surviving across separate `docker run` invocations —
rather than tripping a permission error before ever reaching that
question. 125/125 tests total (116 unit/adv + 9 integration).

**First real end-to-end run.** `python -m sigma.client` (live smoke
test) confirmed a real Groq response for `gpt-oss-120b` parses against
the applicator's hunk regex. Then `python scripts/run_stage1.py --task
binpacking --generations 5`: Σ proposals, the applicator, the six-gate
admission pipeline, the live sandbox, `score_binpacking`, and the ledger
all executed in sequence for real, not mocked.

| gen | outcome | fitness | why |
|---|---|---|---|
| 0 | improved | −30.0 | first candidate, no prior best to compare against |
| 1 | kept | −33.0 | worse than −30, rejected |
| 2 | improved | −30.0 | tie with current best, adopted per the tie-inclusive rule (`test_loop.py::test_equal_fitness_is_adopted_not_just_better`) |
| 3 | kept | −35.0 | worse, rejected |
| 4 | improved | −28.0 | new best |

Final: best fitness −28.0 (28 bins), daily Σ budget 896→888. Every
outcome label checks out exactly against `delta/loop.py`'s adoption rule
(`fitness = -bins_used`; adopt iff `>= best_fitness`) — verified against
the source line by line, not just plausible-looking. This is the warm-up
(binpacking) pipeline-debugging run per §1.2 of the research-program-guide
— **not** the circle_packing run the paper reports; that's still the
next step.

Also worth noting from the `sigma.client` smoke test (a separate
standalone check, not part of the run above): its example proposal for
circle_packing was `r *= 0.99` — a strictly worse mutation for that task
specifically, since `score_packing` rewards larger radii and the seed
grid has no overlap to fix. One data point on `gpt-oss-120b` free-tier's
early proposal quality, potentially worth a line in the paper's
qualitative discussion of generation-0 behavior.

## Week 3, Day 15 (cont'd) — circle_packing sanity check, checkpoint/resume, B08 (2026-09-24)

Built in a session with no Docker binary and no `GROQ_API_KEY` (confirmed,
not assumed — same disclosed constraint as every other "written here,
validate on your machine" entry in this file). Everything below either
needed no network/sandbox to verify, or is new code that *will* need your
machine to exercise for real.

**Circle-packing `P_0` sanity check (research-program-guide §1.4, Day 15's
last remaining item) — done, host-side, no Docker needed:**
`candidate_packing(26)`'s grid seed scores `{"fitness": 2.1666..., "valid":
True}` against `score_packing`. Matches hand-calculation (6×6 grid, 26 of
36 cells used, `r = 1/12`, `26 * 1/12 = 2.1666...`). This closes Day 15;
Week 3's remaining items are the real experiment (Day 16-20) and the live
ADV suite run (Day 19-21) — see `WEEK3_SETUP.md`, both need your Docker +
`GROQ_API_KEY` machine.

**Checkpoint/resume + graceful budget-exhaustion stop — built, unit-tested,
not yet exercised against a real Sigma budget cap.** The gap this closes:
Day 15's real run showed ~1.6 Sigma calls per generation (8 calls / 5
generations); a full circle_packing run at anything near the guide's
§1.5 budget (~1,000 calls) will not fit inside one day's free-tier request
cap, so `scripts/run_stage1.py` needed to survive being invoked once (or a
few times) per day across several days without losing progress or
crashing ugly on `BudgetExceeded`. Concretely:
- `delta/checkpoint.py`: a small, explicit, non-chained JSON file (deliberately
  *not* reconstructed by replaying the ledger — the ledger doesn't store
  `valid` or the candidate's actual source text, only a digest, so
  re-deriving resume state from it would mean re-implementing `loop.py`'s
  adoption rule a second time, in a different place, with a second chance
  to get it subtly wrong). `run_generations()` is the only writer, right
  after each live adoption decision, so the checkpoint can never disagree
  with the decision that produced it.
- `delta/loop.py`: `run_generations()` gained `start_generation_index` /
  `initial_parent_*` (resume from a checkpoint instead of `P_0`) and
  `stop_exceptions` (a caller-supplied exception tuple that ends the run
  cleanly instead of crashing — deliberately *not* a hardcoded import of
  `sigma.budget.BudgetExceeded` into `delta/`, to keep the Sigma-Delta
  structural separation intact; `scripts/run_stage1.py`, which already
  imports both packages, is what actually passes `(BudgetExceeded,)` in).
- `scripts/run_stage1.py`: auto-resumes from a checkpoint next to the
  ledger file unless `--restart` is passed; new `--seeds 0,1000,2000`
  runs several seed-arms in one sitting (each gets its own
  `<stem>.seedN<suffix>` ledger + checkpoint), stopping the whole batch —
  not just the current arm — the moment the shared daily budget is hit,
  since Groq's cap is process-wide, not per-seed.
- Tests: `tests/unit/test_checkpoint.py` (round-trip),
  `tests/unit/test_loop_resume.py` (the one that matters most:
  interrupt-and-resume produces byte-identical `final_src`/`best_fitness`
  to an uninterrupted run of the same generations), and
  `tests/unit/test_run_stage1_cli.py` (the pure per-seed ledger-path
  helper). 13 new tests, all green. **Not yet exercised against a real
  `BudgetExceeded` from the live Groq API** — the unit tests use a fake
  exception type standing in for it (see `test_loop_resume.py`'s
  docstring on why, same Sigma-Delta-separation reasoning as above); the
  first real multi-day run is what actually proves this end to end.

**ADV Tier B08 (env/secret enumeration) — closed**, per the "cheap,
worthwhile addition" `tests/adv/COVERAGE.md` flagged after Day 15's first
pass. Two layers: `tests/unit/test_launcher.py`'s new
`test_no_env_flag_ever_names_a_secret_variable` (host-only — inspects the
exact argv `build_docker_command()` produces against several fake host
secrets, a complete check since that function has no `--env-file` and no
wildcard env passthrough) and `tests/integration/test_sandbox_smoke.py`'s
new `test_no_host_secrets_reachable_inside_container` (the live-container
empirical companion, same pattern as the other Tier B smoke tests). See
`tests/adv/COVERAGE.md` for the updated tally.

129/129 unit+adv tests green (116 from Day 15's first pass + 13 new).
Integration suite now has 10 cases (was 9), still requires your Docker
daemon to run.

**Open question for you, not resolved here:** the research-program-guide's
§1.5 call-budget math ("population 40, generations 25 = 1,000 mutation
calls per run") assumes a population dimension this loop doesn't have —
Stage 1's actual `run_generations()` is single-winner hill-climbing, one
Sigma call per generation attempt (plus retries on admission rejection).
"25 generations" taken literally would be a far smaller experiment than
the guide intends; matching the guide's *total-effort* budget instead
means something closer to ~600-1,000 actual generations per seed-arm
(using Day 15's observed ~1.6 calls/generation). This needs to be a
deliberate decision recorded in the paper's Methods (same honesty
discipline as the Levenshtein-for-Zhang-Shasha and Groq-for-Gemini
substitutions already logged above), not something silently assumed —
see `WEEK3_SETUP.md`'s first section before starting Day 16.

## Not yet built / not yet run for real (Week 3 remainder onward)

- **The circle_packing experiment itself** (Week 3, Day 16-20) — Day 15's
  real end-to-end run used binpacking (pipeline-debugging only, per
  §1.2/§1.4, not reported in the paper) and the sanity check above only
  scored `P_0` once, host-side, no generations run. Nothing has evolved
  circle_packing yet. Needs: the population/generations call-budget
  decision above resolved, then your Docker + `GROQ_API_KEY` machine —
  see `WEEK3_SETUP.md`.
- **The newly-added B08 test, run for real against a live container** —
  everything else in `tests/integration` (including C04/C06/C10) already
  passed for real on 2026-09-23 per this file's own Day 15 entry above
  (9/9 at the time). `test_no_host_secrets_reachable_inside_container`
  is new since then and has only run host-side-adjacent (i.e. not at
  all against a real daemon) — one more `pytest tests/integration -v`
  on your machine closes this out; see `WEEK3_SETUP.md`.
- **Elite-band vs single-winner ablation** — Week 4, tagged via the
  ledger's `ablation_config` column (present in the schema, unused until
  then).

## Stage 1 exit checklist (research-program-guide §1.6) — progress

- [ ] `P_0` improves measurably over generations on circle packing — blocked on the real experiment (see above)
- [x] Manifest integrity mechanism built and unit-tested (full-run claim comes once real generations run)
- [x] The 8-10 case adversarial suite passes — 13/17 Tier A+C cases tested (exceeds target), Tier A via unit tests, Tier C via unit tests + all 9 integration cases (incl. C04/C06/C10) live-verified 2026-09-23; new B08 bonus test still needs its first live-container run
- [ ] Elite-band vs single-winner ablation — not started (Week 4)
- [x] Ledger chain built and unit-tested (hash chain, tamper detection, lineage/generation queries all verified)
- [x] Sandbox hardening verified on a real Docker daemon
- [ ] Repo clean enough to open-source — in progress
- [ ] Draft written per the paper guide — not started
- [ ] arXiv account / category — not started