# FBEBC — Stage 1 (preprint) build

Implements `fbebc-research-program-guide.md` §1 (Stage 1), using
`fbebc-phase1-implementation-guide.md` as the reference for every mechanism
that carries over unchanged. See `STATUS.md` for exactly what's done and
what's next.

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
    scorer_binpacking.py       warm-up task scorer + fixed instance generator
    scorer_circle_packing.py   primary task scorer        (research-program-guide §1.2, verbatim)
seed/
  binpacking/candidate.py       P_0 for the warm-up task
  circle_packing/candidate.py   P_0 for the primary task   (research-program-guide §1.2, verbatim)
tests/unit/                     49 tests, all against hand-written sources/diffs, no LLM calls
```

Not yet built: `harness/` (sandbox supervisor/child split), `delta/ledger/`,
`delta/control/`, `sigma/client.py`, `tests/adv/`. See `STATUS.md`.

## Running the tests

```bash
pip install pytest
python3 -m pytest -v
```

All 49 tests currently pass.
