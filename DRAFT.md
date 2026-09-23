# FBEBC preprint — working draft

**Status: DRAFT, Week 3 (started 2026-09-24). Do not submit.** Everything
marked `[TODO — needs real run]` depends on the circle_packing experiment
in `WEEK3_SETUP.md`, which has not been executed yet. Everything else
below is written against the actual, currently-built system and should
only need light editing once real numbers exist — not a rewrite.

Per `fbebc-preprint-workshop-paper-guide.md`'s own framing, this guide
"assumes Stage 1's experiment is done or nearly done." It isn't yet. What
follows is deliberately the subset of the paper that doesn't depend on
that outcome, drafted in parallel with the multi-day run rather than
after it, so Week 4's writing time (§1.4, Day 24-26) is editing, not
drafting from zero.

---

## Title (pick one once Results is in — the strongest result should lead)

1. *"Fairness-Bounded Elite-Band Cloning: A Structurally Immutable
   Governance Layer for LLM-Driven Program Synthesis"* — lead with this if
   the elite-band-vs-single-winner ablation (Week 4) is the strongest
   result.
2. *"Score Non-Authorship as a Design Principle for Self-Modifying Code
   Agents"* — lead with this if the barrier-integrity result (the
   scoped ADV suite) is strongest, which — see Safety Analysis below —
   is already the strongest thing this project can currently claim.

## Abstract (150–200 words — template, one sentence pending)

> Large language model (LLM)-driven evolutionary code search has produced
> real results — FunSearch, AlphaEvolve, the Darwin Gödel Machine (DGM) —
> but the governance question of what structurally stops an untrusted
> proposer from corrupting its own evaluation is, per DGM's own safety
> discussion, an open concern rather than a solved one. We present FBEBC,
> a governance layer built around a structural (not merely conventional)
> separation between an untrusted proposer (Σ) and a trusted admission-and-
> evaluation harness (Δ): a six-gate admission pipeline enforcing
> byte-identical immutable code regions, a scoring architecture in which
> the candidate never has write access to its own fitness value (score
> non-authorship), and a frozen, pre-registered edit-distance metric
> recorded independently of any admission threshold. We evaluate FBEBC on
> circle packing (n=26, the same benchmark AlphaEvolve reports on) across
> 3 seeds and [TODO — needs real run: N generations / M total Sigma
> calls], and against a scoped 13-case adversarial suite (Tiers A and C of
> the Phase 1 design's full 24-case taxonomy) plus one Tier B bonus case,
> all of which passed. [TODO — needs real run: one to two sentences on
> the fitness-over-generations result and the elite-band-vs-single-winner
> ablation, stated with the honesty the sample size (3 seeds) actually
> supports — see §5 of the paper guide before writing this.] We make no
> latency or timing-fairness claim: all fitness in this work is
> correctness-only, by explicit design.

## 1. Introduction

Automated program synthesis and improvement via LLM-guided evolutionary
search has moved from a research curiosity to a demonstrated capability.
FunSearch found new constructions in extremal combinatorics by pairing an
LLM with a systematic evaluator over an evolving program population
(Romera-Paredes et al., 2024). AlphaEvolve scaled the same idea to full
codebases, reporting state-of-the-art results across dozens of
mathematical and systems problems, including a sum-of-radii of
approximately 2.635 for the n=26 circle-packing benchmark this paper also
uses (Novikov et al., 2025). Most directly relevant here, the Darwin
Gödel Machine (DGM) applied the same LLM-proposes/evaluator-checks loop
to the agent's own source code, showing that a coding agent can
iteratively rewrite its own scaffolding and improve on SWE-bench and
Polyglot as a result (Zhang, Hu, Lu, Lange et al., 2025).

**The gap.** DGM's own safety discussion is unusually candid, and is the
strongest single piece of evidence that the gap this paper addresses is
real and already recognized by the field: the authors state plainly that
"if evaluation benchmarks do not fully capture all desired agent
properties (e.g., safety and robustness), the self-improvement loop could
amplify misalignment over successive generations," and scope their
mitigations to sandboxing, per-execution time limits, and human oversight
— not to a structural barrier between the proposing process and the
scoring process. That barrier — not merely convention or code review, but
something a proposer cannot bypass by proposing different code — is what
this paper builds and evaluates.

**Contributions.**
1. A six-gate admission pipeline (G0–G5) with byte-identity
   post-conditions on immutable code regions, so that no proposed edit can
   widen its own editable surface, forge its own contract, or reach the
   evaluation harness without passing every gate in a fixed order.
2. A score-non-authorship scoring architecture (Amodei et al., 2016's
   reward-hacking framing, applied structurally rather than as a
   monitored property): the container that runs a candidate's code never
   has access to, or a write path into, its own fitness scalar.
3. A frozen, pre-registered edit-distance metric, recorded before any
   admission threshold is set on it — decoupling the fairness measurement
   from the fairness decision, so the metric cannot be tuned in hindsight
   to justify a particular acceptance rate.
4. [TODO — needs real run] An empirical comparison of elite-band vs.
   single-winner selection under this correctness-only fitness, on a
   controlled benchmark task, at a disclosed, small compute budget.

**What this paper does not claim**, stated here rather than deferred to
Limitations: no latency or timing-fairness result (fitness is
correctness-only by design, §1.1 of our research plan); no large-scale
adversarial red-team, only a scoped 13-case suite; a single benchmark
task (circle packing); a small, free-tier compute budget several orders
of magnitude below AlphaEvolve's. We are not claiming to match
AlphaEvolve's reported result — we are demonstrating that the governance
mechanism holds on a task the field already recognizes, at a small
fraction of the compute.

## 2. Related Work

**Optimization / step-bounding.** Trust-region and clipped-objective
methods (TRPO, Schulman et al., 2015; PPO, Schulman et al., 2017) and
evolution strategies (CMA-ES, Hansen & Ostermeier, 2001) bound how far a
single update step may move a policy or a search distribution, for
*stability* — to keep learning from diverging. FBEBC's bounds (the
byte-identity admission gates, the frozen edit-distance metric) serve a
different purpose: comparison *fairness* between candidates and
structural *containment* of what a candidate can even attempt, not
training stability.

**Population-based selection.** Population Based Training (Jaderberg et
al., 2017) and MAP-Elites (Mouret & Clune, 2015) maintain and select
across a population to trade off exploitation and diversity; AlphaGo Zero
(Silver et al., 2017) uses a single-winner replacement rule, evaluating a
new network against the current best over 400 games and only promoting it
on a ≥55% win margin. FBEBC's Stage 1 default is a deterministic analogue
of that single-winner rule, adapted for a deterministic (non-adversarial,
non-stochastic-self-play) fitness: a child is adopted iff it is attested,
valid, and its fitness is at least the current parent's (ties adopted,
never a decrease) — there is no win-margin threshold because there is no
match-based noise to guard against at this scale. The planned Week 4
ablation contrasts this against an elite-band variant that retains more
than one live candidate, in the spirit of MAP-Elites-style archival
rather than pure truncation, [TODO — the exact elite-band selection rule
is not yet finalized; write it here once it is, before running the
ablation, not after].

**Theoretical self-modification and governance.** This is FBEBC's
strongest point of differentiation. Schmidhuber's Gödel Machine
(Schmidhuber, 2006) accepts unbounded self-rewrite in exchange for
requiring a formal proof of improvement before any rewrite is applied —
verification that is, in general, undecidable for the systems being
built today. Yudkowsky & Herreshoff's tiling agents (2013) show that this
verification problem recurses: a self-modifying agent's decision
procedure must in general trust the proofs of its own successor, and
constructing that trust runs into the Löbian obstacle. FBEBC does not
solve either problem — it sidesteps them by making Δ (the admission and
evaluation harness) a constant function of the run, never itself a target
of modification, so there is no successor verifier and no tiling proof
needed. This is a real trade, stated plainly: FBEBC's improvement ceiling
is bounded by Δ's own fixed expressiveness, in exchange for a
verifiable, decidable barrier — a different point on the same design
space DGM occupies without (yet) building a structural barrier, and that
Soares, Fallenstein, Yudkowsky & Armstrong's corrigibility work (2015)
argues cannot be achieved by incentives alone: their Theorem 6 shows that
utility penalties do not stop a sufficiently capable subagent from
circumventing a safety constraint it can reason about, which is the
argument for making the constraint structural rather than incentivized —
concretely, for FBEBC, never exposing budget counters, remaining-
generation counts, or wall-clock deadlines to candidate code. Amodei et
al.'s concrete problems in AI safety (2016) frame the single-scalar
reward-hacking failure mode this targets directly: a system credited for
a scalar it can influence outside the intended channel will learn to
influence that channel. Score non-authorship is this paper's structural
answer to that specific failure mode.

**SOTA LLM code-agent taxonomy.** Beyond FunSearch, AlphaEvolve and DGM
(above), several recent systems occupy adjacent points in this design
space: OpenEvolve (Sharma, 2025) is an open-source reimplementation of
AlphaEvolve's pipeline; ShinkaEvolve (Lange et al., 2025) improves sample
efficiency through adaptive parent sampling and an LLM ensemble;
CodeEvolve (Assumpção et al., 2025) applies an island-based genetic
algorithm with LLM-driven crossover to the same class of problems,
open-source, specifically to address AlphaEvolve's own closed-source
opacity; AdaEvolve (Cemri et al., 2026) treats evolution as hierarchical
adaptive optimization. None of these report a typed rejection taxonomy,
a frozen pre-registered fairness metric, or a structural (as opposed to
prompted or monitored) barrier between the proposer and its own scoring
— the gap this paper targets is not addressed by throughput or
sample-efficiency improvements alone.

*(Citation-checking note for whoever finalizes this: every citation above
was checked against a primary or near-primary source in this drafting
session — venue, year, and the specific claims attributed to each paper.
The AlphaGo Zero 55%-margin figure, DGM's safety-discussion quote's
substance, and the AlphaEvolve n=26 circle-packing figure were all
independently confirmed, not recalled from memory. Still: re-verify
against the primary source immediately before submission per the paper
guide's own checklist — this session's searches are dated 2026-09-24 and
arXiv preprints do get revised.)*

## 3. Method

**3.1 Σ-Δ separation.** Σ (the untrusted proposer — in this build, an LLM
accessed via API) only ever produces text: a unified-diff-style
SEARCH/REPLACE hunk against the current parent source. That text has no
execution privilege of any kind until it has passed every gate below.
There is no code path — no `eval`, no dynamic import, no privileged
runtime update — by which a byte Σ emits becomes an executed instruction
without transiting all six gates (Phase 1 design's invariant I2). This is
enforced structurally: `delta/` (Δ) contains no import of, or reference
to, anything from Σ's own package.

**3.2 The six-gate admission pipeline.**

| Gate | Checks | Enforced or recorded |
|---|---|---|
| G0 Parse | The diff parses as a well-formed SEARCH/REPLACE hunk against the current parent | Enforced |
| G1 Boundary | The edit's post-conditions hold: every immutable region (outside the `EVOLVE-BLOCK` markers) is byte-identical before and after, and the marker set itself is unchanged | Enforced |
| G2 Contract | The pinned function's signature and annotations are unchanged; no new imports are introduced inside the block | Enforced |
| G3 Capability | An AST-level filter denies a fixed set of disallowed names/imports/attributes (a telemetry/efficiency filter, explicitly *not* the security boundary — the kernel-level sandbox, §3.4, is) | Enforced |
| G4 Fairness metric | Frozen AST edit-distance from both the immediate parent and from `P_0` is computed and recorded | Recorded only, not enforced, in Stage 1 (research-program-guide §1.4's explicit scope cut) |
| G5 Integrity re-check | Δ's own on-disk manifest digest is re-verified immediately before the candidate is handed to evaluation | Enforced; failure halts the whole run rather than rejecting one candidate |

G0 and G1 share one implementation: the bounded applicator does not trust
its own patching logic, it trusts the post-condition it checks
afterward. A rejection at G0–G3 returns a typed, sanitized error to Σ as
feedback for its next proposal (Phase1 design §6's rule: describe what
was wrong with the candidate's own diff, never how the gate that caught
it works internally). A G5 failure is categorically different: it means
Δ itself — not the candidate — changed during the run, and the correct
response is to halt immediately and mark the current generation and all
descendants unattested (invariant I1, Fixity), not to reject and
continue.

**3.3 Frozen edit-distance metric.** The metric in G4 (AST edit
distance, approximated as Levenshtein distance over a linearized
canonical-AST node sequence rather than true Zhang-Shasha tree edit
distance — a disclosed, cheaper substitution; see Limitations) is frozen
and recorded before any run has produced mutation data to tune it
against, and before any threshold decision is made on it. This ordering
is deliberate and methodologically load-bearing: a fairness metric
chosen or tuned after seeing what a system's outputs look like is a
metric that can be shaped, consciously or not, to justify a convenient
acceptance rate. Freezing it first, and recording-not-enforcing it in
Stage 1, keeps the measurement honest even though Stage 1 makes no
admission decision from it yet.

**3.4 Selection: single-winner (Stage 1 default) vs. elite-band (Week 4
ablation).** Stage 1's generation loop is single-winner hill-climbing: at
each generation, Σ proposes one diff against the current parent; if
admitted and the resulting evaluation is attested and valid, it becomes
the next parent iff its fitness is at least the current parent's (ties
adopted). This is the same shape as AlphaGo Zero's checkpoint-replacement
rule, adapted for a deterministic fitness signal rather than a
stochastic win-rate over matches. [TODO — needs Week 4] The ablation's
other arm retains more than one live candidate across generations,
testing whether that reduces sensitivity to evaluation noise relative to
single-winner truncation — write the exact selection rule here once
finalized, before running it.

**3.5 Sandbox and isolation (Stage 1 scope).** Docker with explicit
hardening flags (`--network=none`, `--read-only`, `--cap-drop=ALL`,
`--pids-limit`, plus `--ipc=none`, `--cgroupns=private`,
`--security-opt=no-new-privileges` at no extra engineering cost), not
gVisor and not bare metal. This is a disclosed, stated scope cut: Docker's
isolation is weaker than gVisor's, and is judged sufficient here because
the adversary under test is an undirected optimizer proposing plausible-
looking code, not a targeted human attacker — and because Stage 1 makes
no timing claim, so the isolation bar that motivates bare-metal execution
in a timing-fair design does not apply.

## 4. Safety Analysis

We evaluate a scoped adversarial suite against the Phase 1 design's full
24-case, 5-tier taxonomy, covering Tier A (structural boundary) and Tier
C (reward-hacking) — the two tiers directly relevant to a correctness-
only, no-timing fitness function — plus one Tier B case added as a
low-cost bonus. **13 of 17 Tier A/C cases are directly tested** (exceeding
the research plan's 8–10 case target); the remaining 4 (all Tier C: C01
timer-patching, C03 oracle-file reading, C07/C08 held-out-instance
branching) are explicitly out of scope rather than silently skipped —
Stage 1's fitness has no latency dimension to protect (C01) and neither
task has an oracle file or a held-out/visible instance split for a
candidate to exploit (C03, C07, C08), so these attacks have no surface to
land on in this design, not "untested and hoped-safe."

All 9 live-container integration tests (Tier B smoke tests plus the Tier
C cases requiring kernel-level isolation to test meaningfully — state
survival across container invocations, empty-output-after-early-exit,
oversized-payload handling) passed against a real Docker daemon (native
Docker Engine inside WSL2 Ubuntu, confirmed not to be Docker Desktop's
WSL2 integration) on 2026-09-23. [TODO — one more `pytest tests/integration
-v` run needed to confirm the newly-added B08 case (host-secret
enumeration) also passes for real; everything else in this paragraph is
already a real, dated result, not a projection.]

Of the five invariants (I1 Fixity, I2 Non-naturalistic dualism, I3 Score
non-authorship, I4 Provenance, I5 Interruptibility), four are directly
tested at this scale: I1 by the ledger's own chain-verification plus the
manifest re-check at G5 and post-evaluation; I2 by a static import-graph
argument (no module under `delta/` imports from Σ's package) plus the
Tier A suite; I3 by the host-side score-non-authorship envelope checks
plus the live score-smuggling integration test; I4 by the hash-chained
ledger's lineage-walk test. I5 (interruptibility) is implemented — a
control channel that can halt or drain a run, invisible to candidate
code, per Soares, Fallenstein, Yudkowsky & Armstrong's corrigibility
argument that this must be structural rather than incentivized — but is
not yet covered by a dedicated randomized-SIGTERM-injection test the way
Tier E of the full design calls for; state this honestly as a partial
result for I5, not a completed one.

## 5. Experimental Setup [mostly TODO — needs real run]

- Task: circle packing, n=26 (Novikov et al., 2025's benchmark choice) —
  see §1.2 of the research plan for the exact `candidate_packing` /
  `score_packing` definitions, reproduced verbatim from that design.
- Σ model: `openai/gpt-oss-120b` via Groq's free tier — a disclosed
  substitution for the original Gemini 2.5 Flash-Lite pin (free-tier
  model availability moved between planning and building). [TODO: state
  the exact access date range once the real run's dates are known —
  free-tier models can be updated silently by the provider, so the date
  range is a real reproducibility signal, not a formality.]
- Population/generation budget: research-program-guide §1.5 sizes this
  experiment as "population 40, generations 25 → 1,000 mutation calls per
  run" — a calculation that assumes a population sampled each generation.
  This build's actual selection loop (§3.4) is single-winner
  hill-climbing with no population dimension: one Sigma call per
  generation attempt, plus retries on admission rejection. We therefore
  translate the guide's total-effort budget rather than its literal
  generation count, using our own measured ~1.6 calls/generation from
  pipeline-debugging on the warm-up task: **3 seeds, 600 generations
  target each.** [TODO: report the *actual* total call count and
  generations completed per seed once the run finishes — these will not
  exactly match the 600 target if any arm stalls out on repeated
  admission rejections or exhausts the daily request budget before
  reaching it; report the real number, not the target.]
- Compute environment: Docker on a personal machine (WSL2 Ubuntu, native
  Docker Engine — see §3.5), explicitly not gVisor or bare metal,
  explicitly no timing measurement of any kind.
- Total cost: $0 (free-tier LLM access, personal compute) — worth stating
  plainly as a fact about the accessibility of this kind of governance
  research, not something to downplay.

## 6. Results — [TODO, entirely pending the real run]

Do not draft this section with placeholder numbers. Once the run in
`WEEK3_SETUP.md` finishes, produce, in order:
1. Fitness-over-generations curve, all 3 seeds, small multiples or
   overlaid with the individual seed values visible (not just a mean —
   see the paper guide's §5 on statistical honesty).
2. Rejection taxonomy breakdown (counts per `AdmissionError` code —
   already logged in the ledger for every rejected candidate, so this is
   a query against real data, not a new measurement).
3. Elite-band vs. single-winner ablation (Week 4) — report individual
   seed results, frame as suggestive rather than conclusive given N=3,
   per the paper guide's explicit statistical-honesty guidance.
4. Barrier-integrity table: the 13 (+1 bonus) ADV cases, pass/fail, one
   row each — this table can actually be drafted now from §4 above and
   `tests/adv/COVERAGE.md`; only the newly-added B08 row needs its final
   live-run checkmark.

## 7. Limitations

- No latency or timing-fairness evaluation; all fitness in this work is
  correctness-only, by explicit design (§1.1 of the research plan).
- Single benchmark task (circle packing, n=26); generalization to other
  domains untested.
- [TODO] Small compute budget — state the exact total call count and
  generation count actually achieved, once known; note this limits
  statistical power, especially for the Week 4 ablation.
- Reduced adversarial suite: Tiers A and C only (13 of the full design's
  24 cases across 5 tiers), no live red-team campaign. Four Tier C cases
  (C01, C03, C07, C08) are structurally out of scope for this task suite
  rather than tested — state this as "not applicable to this design," not
  "passed."
- Docker-based isolation, not gVisor or hardware-virtualized; the
  security boundary is weaker than a production deployment would need. The
  adversary modeled here is an undirected LLM proposer, not a targeted
  human attacker.
- A single free-tier model (`openai/gpt-oss-120b` via Groq) as Σ; results
  may not generalize to stronger, weaker, or differently-trained models.
- The AST edit-distance metric is Levenshtein distance over a linearized
  canonical-AST node sequence, not true Zhang-Shasha tree edit distance —
  a cheaper proxy that is reasonable for small single-block diffs but can
  diverge from the "real" tree-edit notion for large subtree
  reorderings.
- I5 (Interruptibility) is implemented but not yet covered by a dedicated
  randomized-interruption test at the scale the full design's Tier E
  calls for — a partial result, not a completed one.
- FBEBC is not a universal self-improver: its ceiling is bounded by Δ's
  own fixed expressiveness. This is a deliberate trade against
  unbounded-but-undecidable self-rewrite (Gödel Machines), stated here as
  a design position, not discovered as a shortcoming.

## 8. Future Work

Stage 2 (already planned, not speculative — see
`fbebc-research-program-guide.md` §4) applies the same governance
mechanism to a real production system's agent configuration: evolving
role-prompt text (already treated as data, fetched at runtime, not
executed as source, in the target system's own architecture) rather than
Python source, against the target system's existing eval suite as the
Δ-scorer, with every promotion gated on human PR review. This reintroduces
latency/cost as a legitimate fitness dimension, since it now has real
operational meaning (cheaper-at-equal-quality is a real margin
improvement), and moves from a toy benchmark to real deployment evals as
the fitness oracle.

## 9. Reproducibility statement

Full code will be released at [repo URL] under [TODO: pick a license].
Exact seeds are logged per run in the ledger (`delta/ledger/chain.py`);
exact Σ model identifier and access date range: [TODO, from the real
run]. Note explicitly: reproduction depends on the free-tier model
provider not having changed the model's behavior behind that identifier
since the access date — this is a real limitation of reproducibility for
this entire line of research (every system in §2's SOTA taxonomy that
uses a hosted API model shares it), not unique to this paper, and is
disclosed here rather than assumed away.

---

## Pending items before this draft is submission-ready

- [ ] Run the real circle_packing experiment (`WEEK3_SETUP.md`) — unblocks §5, §6, part of §7, the Abstract's finding sentence, and the Title choice.
- [ ] Run the Week 4 elite-band-vs-single-winner ablation — unblocks Contribution 4, §3.4's elite-band rule, and part of §6.
- [ ] Re-run `pytest tests/integration -v` to confirm the B08 case for real — closes the one open row in §4/§6.4.
- [ ] Final citation-check pass on every reference in §2 immediately before submission (see the citation-checking note there).
- [ ] Pick and record: license for the public repo, exact model access date range, arXiv category/endorsement plan (paper guide §4.2–4.3).
