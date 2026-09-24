# FBEBC — Stage 1 (preprint) build

Implements `fbebc-research-program-guide.md` §1 (Stage 1), using
`fbebc-phase1-implementation-guide.md` as the reference for every mechanism
that carries over unchanged. See `STATUS.md` for exactly what's done and
what's next, `WEEK2_SETUP.md`/`WEEK3_SETUP.md` for the steps that need a
real Docker daemon and Sigma API key on your own machine.

## Layout

```
delta/
  admission/
    blocks.py        EVOLVE-BLOCK parser              (Phase1 §7.1, unchanged)
    applicator.py     bounded SEARCH/REPLACE applicator (Phase1 §7.2, unchanged)
    contracts.py      signature/import contract check   (Phase1 §7.3, PINNED generalized to per-task)
    static_gate.py    AST capability filter (G3)        (Phase1 §6.1, unchanged, NOT a security boundary)
    metrics.py        frozen AST edit-distance (G4)      (Phase1 §7.4, tree-edit-distance -> Levenshtein, disclosed)
    errors.py         shared AdmissionError + taxonomy   (factored out; see file docstring)
    tasks.py          Stage 1's two-task registry        (research-program-guide §1.2)
  integrity/
    manifest.py       SHA-256 manifest + verify()        (Phase1 §5, unchanged)
  evaluation/
    launcher.py                Docker sandbox launcher (basic hardening, research-program-guide §1.1)
    envelope.py                score non-authorship + rigged-numeric checks on raw sandbox output
    evaluate.py                per-candidate cycle: sandbox -> score -> ledger append
    scorer_binpacking.py       warm-up task scorer + fixed instance generator
    scorer_circle_packing.py   primary task scorer        (research-program-guide §1.2, verbatim)
  ledger/
    chain.py, schema.sql       hash-chained provenance ledger (Phase1 §11, Stage-1-scoped columns)
  control/
    channel.py                halt/pause/resume, host-side only (Phase1 §12, unchanged)
  orchestrator.py              admit_candidate(): sequences gates G0-G5
  loop.py                      run_generations(): the actual per-generation cycle, with
                                checkpoint/resume + graceful daily-budget-exhaustion stop
  checkpoint.py                explicit resume-state file for multi-day runs (see loop.py)
  selection.py                 EliteBand: k=1 is single-winner, k>1 the elite band (the ablation's one parameter)
harness/                       supervisor/child process split that runs inside the container
sigma/
  client.py                    Sigma LLM client (Groq, disclosed substitution for the guide's Gemini pin)
  budget.py                    local daily request + token budget, checked before every network call
  prompts.py                   system prompt + per-task objective descriptions
seed/
  binpacking/candidate.py       P_0 for the warm-up task
  circle_packing/candidate.py   P_0 for the primary task   (research-program-guide §1.2, verbatim)
scripts/
  run_stage1.py                 CLI entrypoint: matched-arm, least-progressed-first, multi-day resumable runs
  usage_report.py               measure real Sigma tokens/call; project experiment size from the daily caps
  summarize_ledgers.py          read-only per-arm progress, rejection taxonomy, matched-generation comparison
tests/
  unit/                         194 tests total (with tests/adv), no LLM/Docker calls
  adv/                          scoped adversarial suite, host-only (see COVERAGE.md)
  integration/                  needs a real Docker daemon (see WEEK2_SETUP.md/WEEK3_SETUP.md)
```

## Running the tests

```bash
pip install pytest
python3 -m pytest -v                  # 194 passed — unit + adv, no Docker/LLM needed
pytest tests/integration -v           # needs a real Docker daemon, see WEEK2_SETUP.md
```

## Running a real generation loop

```bash
export GROQ_API_KEY=...
python scripts/run_stage1.py --task binpacking --generations 5   # pipeline smoke test
# the real experiment -- N comes from measuring tokens/call first (WEEK3_SETUP.md §3-4):
python scripts/run_stage1.py --task circle_packing --conditions single_winner,elite_band \
    --band-size 3 --seeds 0,1000,2000 --target-generations <N> --ledger runs/week3.db
```

`--target-generations` is a TOTAL per arm (re-run the identical command daily to
continue); `--generations` means "N more" and is for smoke tests only. See
`WEEK3_SETUP.md` for the measure -> pre-register (`PREREGISTRATION.md`) -> launch
workflow, and why the run is sized by tokens/day rather than requests/day.
