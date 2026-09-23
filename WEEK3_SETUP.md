# Week 3 setup — run this on your WSL2 box

Everything referenced here (checkpoint/resume, the budget-aware CLI, the
B08 tests) was written and unit-tested in a session with no Docker binary
and no `GROQ_API_KEY` (confirmed, not assumed). 129/129 unit+adv tests
green (`pytest` from repo root). What's still untested is anything that
needs a real Docker daemon and a real Sigma budget — that's what this file
walks through, same spirit as `WEEK2_SETUP.md`.

## 0. Decide the call-budget question before spending any real quota

Read this before running anything below — it changes what number you pass
to `--generations`.

`research-program-guide` §1.5 sizes the experiment as "population 40,
generations 25 → 1,000 mutation calls per run." That math assumes a
population sampled each generation. Stage 1's actual `run_generations()`
(`delta/loop.py`) is single-winner hill-climbing: **one Sigma call per
generation attempt** (plus up to `max_retries_per_generation` extra calls
if the admission gates reject a proposal). There is no population
dimension in this loop — "generations=25" taken literally would run only
25 proposals total, a far smaller experiment than the guide intends.

Day 15's real binpacking run is your only real data point so far: 5
generations consumed 8 Sigma calls (896 → 888 remaining), i.e. **~1.6
calls per generation** on that run. Using that ratio, matching the guide's
*intended total effort* (not its literal generation count) means:

```
1,000 calls (guide's target)  /  1.6 calls-per-generation  ≈  625 generations per run
```

**Recommendation:** pass `--generations` in that neighborhood (round to
600 or whatever's convenient) as the *target total* for each seed-arm, not
as one invocation's argument — `--generations` means "attempt this many
more generations this invocation," and the CLI now resumes automatically
across multiple invocations (see §2). Whatever you decide, **write it down
now** and state it plainly in the paper's Methods section, next to the
Levenshtein-for-Zhang-Shasha and Groq-for-Gemini substitutions already
disclosed in `STATUS.md` — this is the same kind of honest, scoped
reinterpretation, not a silent one. Two reasonable alternatives if 625
generations/arm doesn't fit your week:

- Fewer generations per arm, stated as a smaller compute budget than the
  guide's reference point (same honesty move §1.5 itself makes about
  n=26 vs. AlphaEvolve's compute).
- Fewer seeds (2 instead of 3) rather than fewer generations per seed, if
  you'd rather each arm get a real chance to show improvement over many
  generations than run three short arms.

Whatever you pick, the daily request cap (`sigma/client.py`'s
`DEFAULT_DAILY_REQUEST_CAP = 900`, conservative) means a single seed-arm
at ~600-1,000 generations will very likely span more than one day even on
its own — budget for that.

## 1. Pull this session's new files into your clone

New: `delta/checkpoint.py`, `tests/unit/test_checkpoint.py`,
`tests/unit/test_loop_resume.py`, `tests/unit/test_run_stage1_cli.py`.
Modified: `delta/loop.py` (new optional resume/stop-exception parameters,
fully backward compatible — nothing about the Week 2 behavior changed
when these aren't passed), `scripts/run_stage1.py` (auto-resume,
`--seeds`, `--restart`), `tests/unit/test_launcher.py` and
`tests/integration/test_sandbox_smoke.py` (B08), `tests/adv/COVERAGE.md`,
`STATUS.md`. Confirm:

```bash
pytest -v   # should show 129 passed, all in tests/unit and tests/adv
```

## 2. Run the real circle_packing experiment

```bash
export GROQ_API_KEY=...   # never on the command line, never committed

python scripts/run_stage1.py --task circle_packing \
    --seeds 0,1000,2000 --generations 600 \
    --ledger runs/week3.db
```

This creates `runs/week3.seed0.db`, `runs/week3.seed1000.db`,
`runs/week3.seed2000.db` (and a matching `.checkpoint.json` next to each).
It runs seed 0 for up to 600 generations, then seed 1000, then seed 2000
— **stopping the whole batch, not just the current arm**, the instant the
shared daily budget is exhausted (Groq's cap applies to your account, not
per seed-arm). When that happens the script prints which seed it stopped
on and exits with code 3.

**Re-run the exact same command on later days** (same `--ledger`, same
`--seeds`, same `--generations`) to continue — each arm resumes from its
own checkpoint automatically; you do not need to track how many
generations already ran or reduce `--generations` yourself. Pass
`--restart` only if you deliberately want to throw away progress and
start an arm over from `P_0`.

Watch the per-generation output as it runs — `outcome=stalled` for many
consecutive generations in a row is worth a look before you let it run
unattended for hours (it likely means the applicator/contract checks are
rejecting most of what Σ proposes for this task; `sanitize_rejection`'s
feedback should usually let Σ correct course within a few retries).

## 3. Run the scoped ADV suite for real

```bash
pytest tests/adv -v          # host-only, already green without Docker
pytest tests/integration -v  # needs your live Docker daemon
```

Everything except the new B08 test already passed for real on 2026-09-23
per `STATUS.md`'s Day 15 entry (9/9 at the time). The one thing that
hasn't run against a real daemon yet is
`test_no_host_secrets_reachable_inside_container`
(`tests/integration/test_sandbox_smoke.py`) — expect it to pass; if it
doesn't, that's real signal about your Docker setup, not a code bug to
paper over (same rule `WEEK2_SETUP.md` states for the other isolation
tests).

## 4. What this does and doesn't tell you about resume correctness

`tests/unit/test_loop_resume.py` proves, with fakes, that interrupting a
run and resuming it from a checkpoint produces byte-identical
`final_src`/`best_fitness` to an uninterrupted run of the same
generations. It does **not** exercise a real `BudgetExceeded` from the
live Groq API — the first genuinely multi-day run in §2 is what actually
proves this end to end. If day 2's resumed run doesn't pick up where day
1 left off (wrong generation number, wrong parent, budget message
missing), stop and debug before trusting any of the run's numbers; don't
just restart with `--restart` and lose the data.
