# Build status

## Week 1 (research-program-guide §1.4) — DONE, tested, all 49 tests green

| Day | Planned | Status |
|---|---|---|
| 1-2 | Repo scaffold, `P_0` seed for both tasks, manifest builder (unchanged) | Done. `seed/binpacking/candidate.py`, `seed/circle_packing/candidate.py` (verbatim from the guide), `delta/integrity/manifest.py` (verbatim). |
| 3-5 | EVOLVE-BLOCK parser + bounded applicator (unchanged) + contract verification. Unit-test against hand-written diffs, no LLM. | Done. `blocks.py`, `applicator.py` verbatim; `contracts.py` ported with `PINNED` generalized to a per-task parameter (Stage 1 runs two tasks, the guide's version assumed one). 33 hand-written-diff tests across `test_blocks.py`, `test_applicator.py`, `test_contracts.py`, covering ADV-Tier-A-style attacks (boundary violation, marker injection, ambiguous match, contract violation) without needing the ADV harness yet. |
| 6-7 | Frozen AST edit-distance metric, frozen now before any mutation data exists. | Done, with one **disclosed deviation**: the guide calls an unspecified `_zhang_shasha_or_levenshtein` and says "supply your implementation." We supplied Levenshtein distance over the linearized canonical-AST node sequence, not true Zhang-Shasha tree edit distance. This is documented in `metrics.py`'s module docstring and must be stated in the paper's Methods/Limitations section per the guide's own honesty rules — it's a different, cheaper notion of tree distance that's a fine proxy for small single-block LLM diffs but can diverge for large subtree reorderings. |

Bonus, pulled forward from Phase 1's build order (§16, step 1.3, listed as parallelizable): `static_gate.py` (G3), unchanged, with its own "not a security boundary" caveat preserved.

## Not yet built (Week 2 onward)

- **Docker sandbox** (`harness/supervisor.py`, `harness/child.py`, launch command, Dockerfile) — Week 2 Day 8-9. **This needs to run on a real Linux or WSL2 box** (research-program-guide §1.3: "not macOS/Windows Docker Desktop — the VM layer breaks the isolation semantics you're testing"). This chat's sandbox has no Docker daemon, so I can write the code here but it can only be *run and validated* on your own machine.
- **Ledger** (`delta/ledger/chain.py`, `schema.sql`) — Week 2 Day 10-11. Pure Python + SQLite, no Docker needed — this one I *can* fully build and test here.
- **Wiring G0-G3 into one admission pipeline function**, recording G4 metrics without enforcing a threshold, plus G5 (integrity re-check) — Week 2 Day 10-11.
- **Σ client against Gemini free tier + rejection-feedback loop** — Week 2 Day 12-14. Needs a real API key (yours, not mine) and network egress to `ai.google.dev`, which this container's egress allowlist doesn't currently include.
- **Control channel** (`delta/control/channel.py`) — small, pure Python, portable from Phase1 §12 unchanged.
- **The 8-10 case scoped ADV suite** (Tiers A + C) — Week 3 Day 19-21, but several Tier-A-equivalent cases are already effectively covered by the unit tests above; Tier C (reward-hacking: timer patch, direct score write, oracle theft, etc.) needs the sandbox to exist first, since it's about what a candidate running *inside* the container can and can't do.

## Stage 1 exit checklist (research-program-guide §1.6) — progress

- [ ] `P_0` improves measurably over generations on circle packing — blocked on Σ client + mutation loop
- [x] Manifest integrity mechanism built and unit-tested (full-run claim comes once real generations run)
- [ ] The 8-10 case adversarial suite passes — partially covered by unit tests; needs the sandbox for Tier C
- [ ] Elite-band vs single-winner ablation — not started (Week 4)
- [x] Ledger chain design ported (implementation next)
- [ ] Repo clean enough to open-source — in progress
- [ ] Draft written per the paper guide — not started
- [ ] arXiv account / category — not started
