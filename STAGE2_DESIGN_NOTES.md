# Design notes — multi-test evaluation, specialist archives, recombination

**Status: ideas only. Nothing here is built, pre-registered, or being run.**
Recorded so the thinking isn't lost. The Stage 1 experiment
(`PREREGISTRATION.md`) is unchanged by this file.

## 0. Guardrails (read first)

- **Not part of Stage 1.** The research-program guide's "do not" list bans a
  second benchmark task "for robustness" during Stage 1, and the running
  experiment is pre-registered. Adding tests = a new experiment.
- **Relationship to the guide's Stage 2.** The guide's Stage 2 is the
  MiniMe-integrated plan (§4: evolve role-prompt *text* against the real eval
  suite, cost/latency back in the fitness, human PR review on every promotion),
  gated on four business conditions (§3). This idea is **not** that plan, but it
  fits it unusually well (§2 below) and can be adopted into it. The guide's
  rule stands: *don't start Stage 2 on momentum from a good Stage 1 result.*
- **Also a candidate for Phase 2 work on the evolver itself** (how selection
  works), independent of the MiniMe integration.

## 1. The idea

1. Evaluate every candidate on **several tests**, not one.
2. Record the **per-test score vector** (ledger), not just a scalar.
3. Keep, in the elite band, both the best **all-rounder** (passes/scores well
   across the suite) and each test's **champion** (a specialist that beats
   everyone on one test even if it does poorly elsewhere).
4. A **recombination** step proposes a **hybrid**: take what makes the
   specialist excel on its test and bring it into the all-rounder.
5. The hybrid is **just another candidate**: same six gates, same sandbox, same
   attestation, evaluated on the *whole* suite. It is kept only if it scores
   better; "it should inherit both parents' strengths" is a hypothesis to
   measure, never an assumption.

Prior art (**all citations to be verified before use**; from memory):
quality-diversity / MAP-Elites (Mouret & Clune, 2015); multi-objective Pareto
selection (NSGA-II, Deb et al., 2002); lexicase selection, which selects on
individual test cases so specialists survive (Spector, 2012; Helmuth, Spector &
Matheson, 2015); genetic-programming crossover; LLM-mediated recombination
(FunSearch, Romera-Paredes et al., 2024; AlphaEvolve, Novikov et al., 2025;
EvoPrompt, Guo et al., 2024).

## 2. Why it is worth writing down

- **A single scalar hides specialists.** Stage 1's fitness cannot tell an
  all-rounder from a program that is brilliant at part of the task.
- **Overfitting / hard-coding risk.** With one fixed instance (circle packing at
  n = 26) a candidate could hard-code a 26-circle answer and score well without
  being a general packer. Several tests make that much harder.
- **It matches the "sector" concept.** Separate editable blocks (sectors) give
  natural boundaries for specialists and for composing them.
- **Stage 2's eval suite is already multi-test.** The MiniMe evals are many
  cases; per-case scores are free data.
- **"Efficiency" becomes real there.** Stage 1 measures only correctness-only
  fitness (no timing, by design). In Stage 2 cost/latency re-enters (guide
  §4.1), so "cheaper at equal quality" becomes a measured axis — the concept's
  efficiency idea has a home.
- **The noise motivation becomes testable.** Stage 1's deterministic scorer
  cannot test the original "elite band reduces sensitivity to evaluation noise"
  claim (`DRAFT.md` §3.4). Stage 2's LLM-judged evals *are* noisy.

## 3. What Stage 1 already taught us (apply these when this is built)

- **Tests must be variants that share the candidate's interface.** A clone is one
  program with one signature; a bin-packing test cannot score a circle-packing
  program. Variants: different `n`, container shapes, objectives — or, in
  Stage 2, different eval cases for the same prompt.
- **An identity/dedupe key must see everything that matters.** Our first
  duplicate rule keyed on a hash blind to constants and names and wrongly
  rejected constant-tuned improvements (deviation D2). Hybrids will stress any
  key; **test keys on real programs, not fakes**, and replay history through
  old/new rules (`scripts/replay_selection.py`) before trusting a change.
- **Edit-size ≠ behaviour change.** The frozen metric is blind to constants and
  names, and a merge is a large step by construction; a strict per-step bound
  (guide: 15%) would block hybrids and, on Stage 1's data, the best improvement
  too. Decide *in advance* how bounds treat merges.
- **Σ calls are the scarce resource** (~100/day on the free tier); sandbox
  evaluations are cheap. Extra tests cost CPU; recombination steps cost Σ calls.
- **Pre-register** the aggregation rule, band composition, merge operator and
  stopping rule *before* running, and record deviations as we did (D1, D2).

## 4. Open design questions

| Question | Options | Current leaning |
|---|---|---|
| Aggregation across tests | normalized sum; Pareto front; lexicase | Try lexicase and normalized-sum head to head; they fail differently |
| What is a "specialist"? | top score on ≥ 1 test; top-m per test; Pareto-optimal only | Top per test, capped so specialists cannot crowd out the all-rounder |
| Band composition (k slots) | all top-k by aggregate; 1 all-rounder + specialists | 1 all-rounder + specialist slots; k fixed in advance |
| Credit assignment: which edit made the specialist excel? | infer from diffs; **transplant ablation** | Transplant that edit alone onto the all-rounder and measure — never infer from scores |
| Merge operator | diff transplant (re-apply SEARCH/REPLACE); Σ-mediated merge prompt; sector-level swap | Start with diff transplant (free, no Σ call); Σ-mediated as the second arm |
| When to merge | every m generations; on plateau | Every m generations, m fixed in advance |
| Step bound for merges | exempt; bound relative to the *parents* | Report both; decide before running |
| Measuring benefit | hybrid vs best parent on every test | "Hybrid ≥ best parent on the aggregate" *and* the per-test breakdown |

## 5. Smallest experiments, in order (only if/when authorised)

- **E0 — zero-token check on data we already have.** Re-score the clones
  collected in Stage 1 at other `n` (needs the scorer/harness parameterised by
  `n`; no Σ calls). Question: do specialists and generalists even exist in our
  data — does the n = 26 hex layout also beat the grid at n = 20 and 32?
- **E1 — multi-`n` fitness, lexicase vs normalized-sum**, no recombination.
- **E2 — diff-transplant hybrids** (no Σ calls to merge); measure hybrid vs
  best parent.
- **E3 — Σ-mediated recombination** vs E2, at equal Σ-call budget.

For each: state in advance what would count as evidence and what would refute.

## 6. When I would drop the idea

- Hybrids rarely beat their best parent (interference dominates), *and* E2/E3 do
  not beat a plain multi-`n` elite band at equal Σ-call budget.
- Per-test champions turn out to be the all-rounder in disguise (no real
  specialists in the data — E0 would show this cheaply).
- The extra machinery cannot be made auditable in the ledger (every hybrid must
  have a traceable pair of parents and a recorded merge operation).

## 7. Non-goals

No change to the running experiment; no second benchmark inside Stage 1; no
claim, in the Stage 1 paper, that recombination helps. The Stage 1 paper says
only that this is future work (`DRAFT.md` §8).
