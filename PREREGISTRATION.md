# Pre-registration — Stage 1 circle-packing experiment (single-winner vs. elite band)

**Purpose.** Same discipline as the frozen edit-distance metric: decide, in
writing and *before any circle_packing generation runs*, what will be run,
how it will be compared, and what will be reported whichever way it comes
out. Commit this file (and tag the commit) **before** the first real run;
the commit hash is then recorded automatically in
`runs/<name>.runmeta.json` on every invocation.

Fields in `[FILL: …]` are decided after the Day-16 token measurement
(`scripts/usage_report.py`) and filled in *before* launch. Everything else is
frozen now. Changes after launch go in the **Deviation log** at the bottom —
never as silent edits above it.

---

## 1. Question and honest framing

Does retaining a small archive of distinct elite candidates (elite band,
k = 3) reach a higher best fitness than single-winner hill-climbing (k = 1),
at an equal number of generations and equal Σ-call quota, on circle packing
(n = 26)?

**What this ablation can and cannot show.** circle-packing fitness is a
deterministic function of the candidate's output — there is *no evaluation
noise* to be robust against. The comparison therefore tests **exploration**
(whether keeping several parents helps escape local optima that a single
incumbent gets stuck in), *not* noise robustness. The paper must not claim
noise robustness from this experiment. (`DRAFT.md` §3.4 says so.)

## 2. Design (frozen)

| Item | Value |
|---|---|
| Task | `circle_packing`, n = 26, fitness = sum of radii, host-computed, correctness-only |
| Conditions | `single_winner` (k = 1) and `elite_band` (k = 3) — same class, same loop, one parameter (`delta/selection.py`) |
| Seeds (arms) | 0, 1000, 2000 → 6 arms (3 seeds × 2 conditions) |
| Seed semantics | `seed_base` fixes the parent-sampling RNG (`random.Random(f"{seed_base}:{g}")`) and the evaluation seed. It does **not** fix Σ: the LLM is stochastic (temperature 0.7) and provider-side non-determinism is not controlled. Pairs share a `seed_base`, **not** a trajectory. |
| Starting point | Every arm starts from the same `P_0` (grid seed, expected fitness 2.1667). `P_0` is scored **in the sandbox** at generation −1 and seeds the selection state, so "improvement" has a measured denominator. |
| Generation | One selection step: up to `max_retries_per_generation` = 3 Σ calls (admission rejections and unusable replies are retried with sanitized feedback and logged). A generation whose retries are all exhausted is `stalled` and counts as a generation. |
| Selection rule | As specified in the header comment of `delta/selection.py` — top-k distinct (canonical-AST fingerprint) attested-valid candidates ever seen, tie-inclusive, parent sampled uniformly from the band. k = 1 reproduces the pre-existing single-winner rule. **Not tuned.** k = 3 is chosen a priori and is the only k run. |
| Round-robin | All 6 arms advance in chunks of `--round-size` = 10 generations, so any early stop leaves the arms matched to within one chunk. |
| Σ model | `openai/gpt-oss-120b` via Groq free tier, `reasoning_effort=low`, `temperature=0.7`, `max_tokens=2048`. One model for **all** arms. [FILL: access date range from `runmeta.json`] |
| Sandbox | Docker, image digest as recorded in `runmeta.json` (must be the same for every arm; if it changes mid-run, log it below). |
| Target generations per arm | [FILL: N — from `usage_report.py --days D --arms 6`; write the computation here] |
| Daily token cap (local) | [FILL: value passed as `--daily-token-cap`] |
| Stopping rule | Stop when **every arm** reaches N, **or** at the end of Day 23 (2026-10-02), whichever comes first. If stopped by the deadline, all analysis is done at G_common = the fewest generations any arm completed. |
| Code freeze | The `delta/`, `harness/`, `sigma/` code and this file are frozen at launch. Any change after the first real generation is logged below with its commit hash and the reason; the manifest digest in the ledger will differ across such a boundary and the paper must say so. |

## 3. Hypotheses

- **H1 (mechanism works).** In each arm, best fitness after N generations exceeds the `P_0` baseline (2.1667). *Refuted for an arm if best == baseline.*
- **H2 (exploratory, directional).** At G_common, the elite-band arm's best fitness is ≥ the single-winner arm's in a majority of the 3 seeds.

H2 is **exploratory and not a significance test.** With 3 pairs, the strongest
statement the data can support is a count ("elite band was higher in x of 3
seeds"). No p-value, no mean ± sd, no confidence interval will be computed or
reported for the ablation (paper guide §5).

## 4. What will be reported, regardless of direction

1. Per-arm: P_0 baseline, best fitness at G_common and at the arm's own final generation, and the running-best curve. Individual seeds shown; no averaging across seeds as the headline.
2. The full rejection taxonomy per arm, including `E_NO_PROPOSAL` (Σ replied but produced no usable diff) reported **separately** from gate rejections (it is a format-following failure, not a barrier event).
3. Scored-invalid packings (sandbox ran fine, fitness 0.0) and any non-`ok` sandbox statuses.
4. Measured Σ calls per generation and total Σ calls / tokens (from `~/.fbebc_sigma_budget.usage.jsonl`, copied into `runs/` at the end).
5. If elite band is **not** better — or is worse — that is reported as the result. A null or negative ablation is a legitimate finding here and is not grounds for changing k, the sampling rule, or the seeds.
6. Any arm that stalls, crashes, or hits an integrity violation, with its ledger evidence.

## 5. Pre-declared analysis limits

- Single task, single Σ model, single k, three seeds: the ablation is *suggestive at most*.
- Because Σ is not seeded, re-running the identical command will not reproduce these trajectories; the ledger (hash-chained, per-candidate source digests) is the reproducibility artifact, not the seed.
- Best fitness is a **running maximum over attested candidates**; it is identical to the band's best member by construction (top-k never evicts its own maximum), so both conditions are plotted on the same definition.

## 6. Deviation log

*(Append only. Date, commit hash, what changed, why, and which results it affects.)*

| Date (UTC) | Commit | Change | Reason | Affects |
|---|---|---|---|---|
| — | — | — | — | — |
