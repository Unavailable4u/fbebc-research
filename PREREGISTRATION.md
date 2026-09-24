# Pre-registration — Stage 1 circle-packing experiment (single-winner vs. elite band)

**Purpose.** Same discipline as the frozen edit-distance metric: decide, in
writing and *before any circle_packing generation runs*, what will be run,
how it will be compared, and what will be reported whichever way it comes
out. Commit this file (and tag the commit) **before** the first real run;
the commit hash is then recorded automatically in
`runs/<name>.runmeta.json` on every invocation.

All design values below were filled from the Day-16 measurements and pilots
before launch (this file is frozen at the `prereg-week3` tag). Everything
here is frozen at launch. Changes after launch go in the **Deviation log** at the bottom —
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
| Σ model & prompt | `openai/gpt-oss-120b` via Groq free tier, `reasoning_effort=low`, `temperature=0.7`, `max_tokens=2048`. One model and **one prompt (v2)** for all arms; the prompt version and SHA-256 are recorded on every invocation in `runmeta.json` (`summarize_ledgers.py` flags a mid-run change). See §7. [Access date range: recorded from `runmeta.json` after the run — a record, not a design choice.] |
| Sandbox | Docker, image digest as recorded in `runmeta.json` (must be the same for every arm; if it changes mid-run, log it below). |
| Target generations per arm | **N = 100** (final; see basis below). [Basis, from the v2 pilot: Basis: Groq's published free-tier limit for this model is 200K tokens/day (30 RPM / 1K RPD / 8K TPM; console.groq.com/docs/rate-limits — verify on your account); measured v1 cost 1,518 tokens/call (p95 1,807), v2 expected ≈ +150; measured 1.0 calls/generation over 14 pilot generations but 1.6 on the binpacking warm-up, so plan on 1.0–1.6. v2 measured **1,754 tokens/call (n = 40; prompt ≈ 1,148)** and **1.00 calls/generation over all 54 pilot generations (0 gate rejections)**. 600 generations × 1.0–1.3 calls × 1,754 ≈ 1.05–1.37M tokens ≈ 5.5–7.2 days at a 190K/day cap; the deadline below keeps it safe if calls/generation is higher.] |
| Daily token cap (local) | `--daily-token-cap 190000` (Groq's published limit is 200K TPD; 10K margin ≈ 5 worst-case calls of overshoot; the provider window may be rolling, so a real 429 can still stop a day early — that is a clean stop, not an error) |
| Stopping rule | Stop when **every arm** reaches N, **or** at the end of Day 23 (2026-10-02), whichever comes first. If stopped by the deadline, all analysis is done at G_common = the fewest generations any arm completed. **N is not extended** after the arms reach it, whatever the results look like (no optional stopping). |
| Code freeze | The `delta/`, `harness/`, `sigma/` code and this file are frozen at launch. Any change after the first real generation is logged below with its commit hash and the reason; the manifest digest in the ledger will differ across such a boundary and the paper must say so. |

## 3. Hypotheses

- **H1 (mechanism works).** In each arm, best fitness after N generations exceeds the `P_0` baseline (2.1667) by more than 1e-9 (the scorer's own tolerance; exact float ties and 1-ulp differences, which occurred in the pilot, are not improvements). *Refuted for an arm if not.* H1 is the guide's Stage 1 exit criterion ("`P_0` improves measurably … even a modest gain is a valid, reportable result") — and it can fail: see §7.
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

## 7. Pilots and the one prompt revision (disclosed before launch)

Before this file was frozen, three small pilots were run, each on its own
throwaway ledger (`runs/measure*.db`, `runs/pilot_v2*.db`), never pooled with
the reported arms:

1. **v1 single-winner, 8 generations, seed_base 0.** 0 strict improvements
   (best = baseline = 2.1667); 3 of 8 candidates were invalid packings
   (fitness 0.0, overlap); the rest were worse or exact ties (e.g. `r = 0.5 /
   side`, algebraically the seed). 1.00 Σ calls/generation, 0 gate rejections,
   1,518 tokens/call.
2. **v1 elite band (k=3), 6 generations, seed_base 0.** 0 strict improvements;
   the band filled with `P_0` and exact-tie variants.
3. Both used prompt **v1**. Diagnosis: the seed's equal-radius grid is a hard
   local optimum for one-line edits (scaling the radius is strictly worse or
   invalid), yet v1 asked for "ONE small, targeted edit" and called the grid
   "a deliberately weak starting point." That wording was inaccurate and
   steered Σ away from the restructuring the task needs.

**v2 pilot result (seed_base 9999, both conditions, 20 generations each, throwaway
ledgers `runs/pilot_v2.*`):** **0 strict improvements in either arm** — best =
baseline = 2.1667 in both (the band arm's best printed 2.166666666666667, one
float ulp above baseline; not an improvement under H1's 1e-9 tolerance). But v2
changed Σ's behavior: it now proposes valid non-grid layouts (fitness 1.9330127
= 1.5 + √3/4, 1.7414 = 1.6 + √2/10) that score *below* the grid, and exact-tie
variants; invalid packings 3/20 (single-winner) and 4/20 (band); 1 candidate
crashed (nonzero exit, no scored result — an ordinary execution failure, not a
barrier event). 1.00 Σ calls/generation, 0 gate rejections. The driver, round-
robin, token cap and checkpoint/resume ran correctly live (12 → 20 continued,
not restarted). Pooled with v1, that is 0 improvements in 54 pilot generations.

**Consequence, per the rule below:** launch anyway. 40 v2 generations cannot
show Σ *cannot* improve (structural proposals now appear, and improvements in
this literature typically arrive after far more samples), and 14 + 40 pilot
generations is not a basis for further tuning. **H1 may well fail in the
reported run, and the ablation would then be uninformative** (both arms flat
at the baseline); the paper would say exactly that.

**Decision (made on 14 generations of v1 data — a small, informal basis, and
disclosed as such):** revise the prompt **once** to v2 (edit size unrestricted
within the block; objective states the all-or-nothing validity rule and that
the grid is a strong local optimum for radius-only tweaks). A v2 pilot
(both conditions, seed_base 9999, ~20 generations each) then checks the
plumbing and gets a first read on whether Σ can now improve at all.

**Rule, frozen now:** *no further prompt changes after the v2 pilot, whatever
it shows.* Iterating the prompt against pilot outcomes until something
improves is a forking-paths procedure and would make H1/H2 uninterpretable.
If v2 also shows no improvement, the experiment is launched anyway and the
paper reports H1 as failed under this Σ/prompt/edit interface. Everything
else in the paper (containment, attestation, ADV suite) does not depend on H1.

**Consequences to state in the paper:** the reported prompt is v2, chosen
after observing v1's behavior; v1 was never run for the reported arms; the
v2 prompt gives Σ more task guidance than v1 (validity rule, "strong local
optimum"), so results are not comparable to an unguided-Σ setting.

## 6. Deviation log

*(Append only. Date, commit hash, what changed, why, and which results it affects.)*

| Date (UTC) | Commit | Change | Reason | Affects |
|---|---|---|---|---|
| — | — | — | — | — |
