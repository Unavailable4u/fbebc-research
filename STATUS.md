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

**(Resolved 2026-09-24 by the Day 16 patch — see the section above; left here for the record.) Open question:** the research-program-guide's
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

## Week 3, Day 15 review → Day 16 patch (2026-09-24): three problems found before the real run, fixed and unit-tested

A read-through of the repo against the three guides, before spending any real
circle_packing quota, found three things that would have wasted or distorted
the Week 3 experiment. All fixed in one patch; **194/194 unit+ADV tests
green (was 129)**, and everything is still "written here, validate on your
machine" — no Docker binary and no `GROQ_API_KEY` in the authoring session
(confirmed, not assumed).

**1. The free-tier *token* cap probably binds before the request cap — an
unmeasured assumption, now measured by tooling.** `sigma/budget.py`'s own
docstring asserted the ~1,000 req/day cap was "comfortably the binding
constraint for this pipeline's small per-request token counts." That was
never measured. The circle_packing prompt is ~870 input tokens (chars/4
estimate, before reasoning/output), so at ~1,200–2,500 total tokens/call the
200K tokens/day figure recorded above (2026-09-17, **unverified on your
account**) would allow only ~80–160 calls/day. Consequences, if it holds: the
literal "3 seeds × 600 generations" plan is many days beyond the 4-week cap,
and the experiment must be sized by tokens. Changes: `sigma/budget.py` tracks
tokens (and can enforce an optional `--daily-token-cap`); `sigma/client.py`
logs every response's `usage` block to `~/.fbebc_sigma_budget.usage.jsonl`
and converts a daily-limit 429 (body says "per day"/TPD/RPD, or Retry-After >
120 s) into `BudgetExceeded` instead of sleeping through it;
`scripts/usage_report.py` prints measured tokens/call and projects
generations/day and generations/arm. **Nothing here has touched the live API.**

**2. `--generations` semantics and arm starvation.** The CLI's `--generations
N` meant "N *more* this invocation", contradicting `WEEK3_SETUP.md` v1 ("re-run
the exact same command"), and arms ran strictly sequentially — seed 0 would
have consumed every day's quota. Now `--target-generations N` is a total per
arm; all arms advance round-robin in chunks of `--round-size` (default 10) so
a quota stop leaves them matched to within a chunk; `--generations` remains
as the legacy smoke-test mode. `--restart` now *archives* (renames) an arm's
ledger+checkpoint instead of appending new records into an old ledger.
Each invocation appends the git commit (+ tracked-dirty flag) to
`<ledger>.runmeta.json`, so the paper can state whether the code was
identical across days.

**3. Elite-band arm undefined; "noise" framing wrong for this task; `P_0`
never scored.**
- `delta/selection.py` (new): one `EliteBand` class, one parameter `k`;
  k=1 is exactly the previous single-winner rule (the pre-existing loop tests
  pass unchanged), k>1 is a top-k archive of distinct (canonical-AST
  fingerprint) attested-valid candidates, parent sampled uniformly,
  deterministic per `(seed_base, generation)` so resume reproduces
  uninterrupted runs. Rule frozen in `PREREGISTRATION.md`.
  **Disclosed simplification:** fixed integer band width, not the Phase1
  guide's fairness-bounded, scheduled band width (that is Phase 2/3).
- circle-packing fitness is **deterministic**, so the ablation tests
  *exploration*, not noise robustness. `DRAFT.md` §3.4/§7 corrected.
- `delta/loop.py`: `P_0` is now evaluated in the sandbox at generation −1
  (`evaluate_baseline=True`, on fresh runs only). Previously the first
  admitted child was adopted even when it scored *below* the seed. (Day 15's
  binpacking smoke run predates this and had no baseline — it is
  pipeline-debugging only and is not reported.)
- Σ replies that contain no usable SEARCH/REPLACE block
  (`SigmaProposalError`) are now logged as **`E_NO_PROPOSAL`** and retried
  instead of crashing the run (auth/network errors still crash loudly).
  Reported separately from gate rejections; not a barrier event.
- Every ledger row now carries `ablation_config` (`single_winner_k1` /
  `elite_band_k3`), which was a dead schema column until now.
- `scripts/summarize_ledgers.py` (read-only): per-arm progress, measured Σ
  calls/generation, baseline vs. best, running best, rejection taxonomy, and
  a matched-generation comparison per seed with individual values only (no
  mean/sd/p-value).

**Not verified by the authoring session (needs your machine):** the token
estimate itself; Groq's real limits and 429 body wording (the daily-limit
detection matches on "per day"/"(TPD)"/"(RPD)" and Retry-After > 120 s —
verify against a real 429 if you ever see one); the whole patch against live
Docker + Groq. The end-to-end multi-day resume path is tested with fakes
only (`test_multiday_matched_run_end_to_end_with_fakes`).

**Known gaps deliberately left:** `E_NO_PROPOSAL` retries still consume Σ
budget like any call; `max_tokens`/`reasoning_effort` are not yet CLI flags
(revisit only if the measurement shows truncation or waste); ledgers are
gitignored and must be archived separately for the public release.

## Day 16 live pilot (2026-09-24): first real circle_packing generations

**What ran (your machine, real Docker + Groq):** patch 1 applied at base
`36ae5c9` (uncommitted, hence `dirty invocations=1`); 8 generations
single-winner and 6 generations elite-band (k=3) on throwaway ledgers.
- Pipeline works end to end on the live stack: `P_0` baseline scored in the
  sandbox = 2.1667 (matches the hand calculation); all 14 candidates ran with
  status `ok`, none unattested; ledger chains verified; **1.00 Σ
  calls/generation** and 0 gate rejections in both runs; usage logging and the
  new arm-tagged ledgers (`single_winner_k1`, `elite_band_k3`) work.
- **Measured tokens: 1,518/call mean, 1,807 p95, 924 prompt + 594 completion
  (428 reasoning), n = 8.** Groq's published limits table (console.groq.com/
  docs/rate-limits, checked 2026-09-24) lists `openai/gpt-oss-120b` at 30 RPM /
  1K RPD / 8K TPM / **200K TPD**, matching the figures recorded above — so
  the token cap does bind (~110–130 calls/day), not the request cap. Your
  account's own limits page remains authoritative.
- **Result to worry about:** 0 strict improvements over `P_0` in 14
  generations. Inspected diffs: `r = 0.99/(2·side)` (worse), `r = 0.5/side`
  (identical value), and a per-circle `r = min(x, 1-x, y, 1-y)` that overlaps
  (invalid → fitness 0). The grid is a hard local optimum for small edits, and
  prompt v1 asked for "ONE small, targeted edit." 14 generations is far too
  few to conclude Σ *cannot* improve; it is enough to see the prompt was
  working against the task.
- **Response:** one disclosed prompt revision (v2) with a no-further-changes
  rule — `PREREGISTRATION.md` §7 — plus a v2 pilot that also live-tests the
  round-robin / target / resume driver (previously simulated with fakes only).
- Minor artifact, not changed: a candidate scored 2.166666666666666 vs the
  baseline's 2.1666666666666665 (1 ulp) and was "kept" rather than adopted;
  ties are decided by float rounding. H1 therefore uses a 1e-9 tolerance.
- Band diversity is *syntactic* (canonical-AST fingerprint): `P_0` plus
  semantically-equivalent rewrites (`0.5/side` ≡ `1/(2·side)`) can fill the
  band with behavioral duplicates. Left as is — the rule is pre-registered —
  and to be disclosed as a limitation.
- **Confirmed at Day 16:** `pytest tests/integration -v` → 10/10 passed against real Docker (22 s), including B08 (`test_no_host_secrets_reachable_inside_container`) — see the v2 pilot section below.

## Day 16 v2 pilot (patch 2 applied, uncommitted): plumbing verified, H1 still open

Ran on your machine: `--conditions single_winner,elite_band --seeds 9999
--target-generations 12` then the identical command with `20`, ledger
`runs/pilot_v2.db`, `--daily-token-cap 190000`; plus `pytest tests/integration -v`.
- **Live-verified:** target-total + round-robin + resume (second command
  continued at generation 12 in both arms; every arm reached exactly 20);
  local token cap plumbing; prompt version/hash in `runmeta.json` (v2, 1 hash);
  ledger chains OK; **integration suite 10/10 (B08 closed)**.
- **Cost measured:** v2 = 1,754 tokens/call (40 calls; prompt ≈ 1,148); 1.00
  Σ calls/generation across all 54 pilot generations; **0 admission
  rejections ever fired on real Σ output** (so the paper's real-run rejection
  taxonomy will be essentially empty; the barrier evidence is the ADV suite).
- **Quality:** 0 strict improvements in either arm (20 gens each). Σ now
  proposes valid non-grid layouts (1.9330127 = 1.5 + √3/4; 1.7414 = 1.6 +
  √2/10) but all score below the seed grid; 3–4 of 20 invalid packings per
  arm; 1 crashed candidate (nonzero exit → no attested result; ordinary
  failure, not an integrity event). A band-arm 1-ulp "improvement"
  (2.166666666666667) is not an improvement under H1's 1e-9 tolerance.
- **Decision:** per `PREREGISTRATION.md` §7, launch unchanged (no further
  prompt changes) at N = 100/arm, 6 arms, token cap 190000, deadline Day 23.
- `git_dirty` in `runmeta.json` now watches only run-affecting code
  (`delta harness sigma seed scripts/run_stage1.py`) — daily doc edits no
  longer make later invocations look dirty. (Pilot invocations were dirty
  because patch 2 was uncommitted; expected.)
- `summarize_ledgers.py` now prints `baseline rows` (must be 1 — the
  once-only baseline check across resumes) and relabels "unattested" as "no
  attested result (crash/timeout, not an integrity event)".

## Launch day (2026-09-24 UTC): the real matched run started; day 1 results; one scheduler bug fixed

Launched at tag `prereg-week3` (`--target-generations 100`, 6 arms, token cap
190000, prompt v2). It stopped cleanly at the local token cap
(190,932 tokens used, incl. 70,142 from the earlier pilot).
- **Progress:** 63 generations across the 6 arms — single_winner/seed0 = 13,
  every other arm = 10 — from 66 Σ calls and 120,790 tokens: **1,830
  tokens/call** (pilot: 1,754; parents grow as Σ writes longer code, so watch
  this number drift up) and **1.05 calls/generation**. Three retried calls
  (elite_band/seed1000: 12 requests for 10 generations; elite_band/seed2000:
  11) mean admission rejections or `E_NO_PROPOSAL` *do* occur on real Σ output
  — classes to be read from `summarize_ledgers.py`, not from memory.
- **First strict improvement:** `elite_band/seed1000` reached **2.2292036**
  (+0.0625, +2.9% over the 2.1667 baseline) within its first 10 generations.
  The other five arms are still at the baseline. **One arm, ten generations,
  and a peek at one arm's result: nothing to conclude, and nothing changes.**
  The run continues to N = 100 unchanged (`PREREGISTRATION.md`: no optional
  stopping, no extension). Worth a read of the winning diff (text only —
  never execute candidate code outside the sandbox) as a qualitative example
  for the paper.
- **Bug found from the counts, fixed:** the arm scheduler was a per-pass
  round-robin that restarts from the first arm on every resume, so early arms
  gain a chunk whenever a daily stop lands mid-pass and the lead accumulates
  (regression test reproduced `[10,10,30,30,30,33]` by day 2). Replaced with
  least-progressed-first (`next_chunk`); 202/202 tests pass, including a
  60-day interrupted-run simulation. Logged as **deviation D1** in
  `PREREGISTRATION.md` — scheduling order only; no arm's trajectory logic
  changed. My earlier claim that arms "stay matched across days" was wrong for
  the previous scheduler; the multi-day fake test only checked the first stop.
- Budget outlook at 1,830 tokens/call and 190K/day: ~104 calls ≈ 99
  generations/day at 1.05 calls/gen → the remaining ~537 generations need
  ~5.5 more days (deadline: end of 2026-10-02).

## Run log (append one row per day the run advances; numbers copied from `summarize_ledgers.py`)

| Date (UTC) | single_winner s0 / s1000 / s2000 (gens; best) | elite_band s0 / s1000 / s2000 (gens; best) | Σ calls / tokens today | Notes |
|---|---|---|---|---|
| 2026-09-24 | 13; 2.1667 / 10; 2.1667 / 10; 2.1667 | 10; 2.1667 / 10; **2.2292** / 10; 2.1667 | 66 launch calls, 120,790 tok (1,830/call) | launch at commit `9c149ea0`, clean; stopped at local token cap; D1 (scheduler) fixed afterwards |

**Day-1 detail worth keeping for the paper**
- Rejections on real Σ output: 3 of 66 calls, **all `E_MALFORMED_DIFF`** (band/seed1000: 2, band/seed2000: 1), none in the three single-winner arms. n = 3; do not read a pattern into "only the band arms" (band parents are more varied and longer, so a verbatim SEARCH block is harder to copy — a hypothesis, not a finding).
- 1 crashed candidate (band/seed2000, `nonzero_exit`, no scored result — ordinary execution failure, not a barrier event). Scored-invalid packings so far: 0–3 per arm of 10–13.
- **The 2.2292 candidate** (`elite_band/seed1000`, generation 9, child of g8): a hexagonal-offset row layout, then each circle's radius set to `min(distance to nearest square border, half the distance to its nearest neighbour)`. That radius rule can never produce an overlap (any pair has `r_i + r_j ≤ d_ij` by construction; checked numerically over 2,000 random point sets, min slack 0.0) — so it is valid *by design*, not by scorer-tolerance luck, and it did not touch the scorer or anything outside the block. It also carries a stale leftover comment from an earlier edit. One example only; when writing §6 show it alongside a *typical* candidate, not on its own.
- Per-call token cost keeps creeping up as parents get longer code (1,830 vs the pilot's 1,754; this run's largest single call 3,069 tokens). Budget check at a pessimistic 2,800 tokens/call: 8 daily quotas (Sep 25 – Oct 2) still cover ~517 of the ~537 remaining generations; the stopping rule (Day 23, analysis at G_common) covers any shortfall. There is ~2.5 days of slack at the current rate — **no timing pressure to start early.**
- All Σ calls run under **one Groq account/key** and its free-tier quota (to be stated in the paper's Methods). The daily wait is deliberate; swapping in other accounts' keys to multiply the quota is not part of this experiment (it works around the provider's usage limits, risks the provider's action against the main key mid-project, and buys nothing given the slack above).

## Day 17: step-size data from the real run, and a bug in MY duplicate rule (patch 6)

**Step-size data** (`ast_distance_parent`, frozen metric, admitted candidates; n = 10–13 per arm — preliminary):

| arm | median step | max step | best-fitness candidate: step / distance from `P_0` |
|---|---|---|---|
| band s0 / s1000 / s2000 | 0.183 / 0.221 / 0.388 | 0.541 / 0.582 / 0.580 | s1000: **0.391 / 0.713** (the 2.2292 hex layout) |
| single s0 / s1000 / s2000 | 0.066 / 0.512 / 0.088 | 0.641 / 0.753 / 0.556 | (best rows are ties with `P_0`) |

- The scale is the whole-file, node-type-sequence Levenshtein normalised by the longer sequence (immutable header ≈ 5 of 122 nodes, negligible dilution). I reproduced the ledger's 0.713 exactly from the printed winner, so the numbers are what they appear to be.
- **Reading, for the concept (bounded small increments):** the guide's planned 15% per-step bound would counterfactually have blocked the winning step (0.391) and most structural proposals; only near-constant tweaks (medians 0.066, 0.088) fit under it. From the seed grid, the hex layout is not reachable in sub-15% steps. That is the familiar trust-region limitation (a bound cannot cross a valley), observed on real data — but n is small, it is counterfactual on realized proposals (blocking a step would change every later parent), and it is one task. Report as an observation, not a result.
- **The frozen metric is blind to constants and identifier names** (verified by running it: `1.0 → 0.99`, `1.0 → 100.0` and `side → kk` all have distance 0.0). A step bound on this metric therefore cannot bound the *magnitude* of a numeric change. Syntactic step size ≠ behavioural step size; the paper should report edit size together with the fitness change and say so in Limitations. (The metric was frozen before data, so this is a disclosed weakness, not something to change.)

**The bug (mine, introduced with the elite-band rule):** the duplicate check used `semantic_fingerprint`, which hashes only node *types*. Two programs differing only in constants/names got the same key, so a **constant-tuned child was rejected as a "duplicate" even when strictly fitter** — in both arms (k=1 included). Numeric tuning of a working layout is the most basic kind of improvement, and it would have become more likely as Σ's programs got richer. I described the key as "canonical-AST hash" and never tested what it could not see; the tests used fakes whose fingerprints I controlled.

**Fix (patch 6):** new `exact_fingerprint` (hash of the full canonical AST: layout/comments/docstrings ignored, constants and names count; keys versioned `x1:`); selection uses it; checkpoints written with the old key are re-derived from stored source on resume. The ledger's `semantic_fingerprint` column and the frozen distance are untouched. 214/214 tests pass, including regressions for constant-tuned improvements under k=1 and k=3.

**Has it already changed anything? — No.** `scripts/replay_selection.py` on all six arms (63 generations): every replay reproduced its arm's checkpoint band exactly (so the replay is faithful), and the corrected rule made **identical decisions on every arm's history** (candidates that reached selection: band 7 / 9 / 6, single-winner 10 / 10 / 10). The fix is a pure bug fix that touched none of the data collected so far, so no restart; logged as **deviation D2** in `PREREGISTRATION.md` and continuing. Output saved as `runs/week3.replay_d2.txt`. Lesson kept: my tests for the rule used fakes whose fingerprints I controlled, so they could not catch a key that was wrong on real programs; the new tests exercise the real `edit_metrics` and real sources.

## Not yet built / not yet run for real (Week 3 remainder onward)

- **The circle_packing experiment itself** (Week 3, Day 16-20) — Day 15's
  real end-to-end run used binpacking (pipeline-debugging only, per
  §1.2/§1.4, not reported in the paper) and the sanity check above only
  scored `P_0` once, host-side, no generations run. Nothing has evolved
  circle_packing yet. Needs: the Day 16 token measurement
  (`WEEK3_SETUP.md` §3) → fill and commit `PREREGISTRATION.md` (§4), then
  your Docker + `GROQ_API_KEY` machine for the matched run (§5).
- **The newly-added B08 test, run for real against a live container** —
  everything else in `tests/integration` (including C04/C06/C10) already
  passed for real on 2026-09-23 per this file's own Day 15 entry above
  (9/9 at the time). `test_no_host_secrets_reachable_inside_container`
  is new since then and has only run host-side-adjacent (i.e. not at
  all against a real daemon) — one more `pytest tests/integration -v`
  on your machine closes this out; see `WEEK3_SETUP.md`.
- **Elite-band vs single-winner ablation** — the arm is now *built* and
  unit-tested (Day 16 patch above) and runs **concurrently** with the
  single-winner arms (matched, round-robin), not as a separate Week 4
  pass; tagged via the ledger's `ablation_config` column. Not yet run for
  real.

## Stage 1 exit checklist (research-program-guide §1.6) — progress

- [ ] `P_0` improves measurably over generations on circle packing — blocked on the real experiment (see above)
- [x] Manifest integrity mechanism built and unit-tested (full-run claim comes once real generations run)
- [x] The 8-10 case adversarial suite passes — 13/17 Tier A+C cases tested (exceeds target), Tier A via unit tests, Tier C via unit tests + all 10 integration tests (incl. C04/C06/C10 and the B08 bonus) live-verified against real Docker (9/9 on 2026-09-23; 10/10 on Day 16)
- [ ] Elite-band vs single-winner ablation — machinery built + pre-registered (`PREREGISTRATION.md`); not yet run
- [x] Ledger chain built and unit-tested (hash chain, tamper detection, lineage/generation queries all verified)
- [x] Sandbox hardening verified on a real Docker daemon
- [ ] Repo clean enough to open-source — in progress
- [ ] Draft written per the paper guide — not started
- [ ] arXiv account / category — not started