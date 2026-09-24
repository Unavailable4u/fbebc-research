# Week 3 setup (v2, rewritten Day 16) — run this on your WSL2 box

Everything here was written and unit-tested in a session with **no Docker
binary and no `GROQ_API_KEY`** (confirmed, not assumed). 194 unit + ADV tests
pass there. What only your machine can verify — real Docker, real Groq — is
called out in each step. Same rule as `WEEK2_SETUP.md`: if a live check fails,
that is real signal about your setup or about an assumption, not something to
paper over.

## Why v1 of this file was replaced

The Day-15 review found three problems that would have wasted the real run:

1. **The token cap, not the request cap, is probably the binding free-tier
   limit.** `sigma/budget.py` counted only requests and assumed ~900/day was
   the constraint. Groq's free tier also caps *tokens/day* (200K for
   `gpt-oss-120b` per `STATUS.md`, as of 2026-09-17 — verify on your account).
   The circle_packing prompt alone is ~870 input tokens; with reasoning and
   output that is plausibly ~1,200–2,500 tokens/call, i.e. **~80–160
   calls/day**, not 900. *(An estimate — step 3 measures it.)*
2. **`--generations 600` did not mean what v1 said.** It meant "600 *more*
   per invocation", and arms ran strictly one after another, so seed 0 would
   have eaten every day's quota while seeds 1000/2000 starved, and re-running
   the same command would have given seed 0 another 600. Now:
   `--target-generations N` is a *total per arm*, and arms advance
   round-robin so any early stop leaves them matched.
3. **The elite-band arm did not exist**, and its stated motivation ("noise
   robustness") does not apply to a deterministic fitness. It now exists
   (`delta/selection.py`, k=1 ≡ single-winner) and is framed as an
   *exploration* test. See `PREREGISTRATION.md`.

Also fixed on the way: **P_0 is now scored in the sandbox at generation −1.**
Before, the first admitted child was adopted even if it scored *below* the
seed, and "did P_0 improve?" had no measured denominator.

## 1. Apply the patch

From your clone (expected base: commit `36ae5c9`):

```bash
cd ~/fbebc-research                      # adjust to your clone path
git status --short                       # should print nothing (or only untracked files)
git rev-parse --short HEAD               # expect 36ae5c9
cp /path/to/fbebc-week3-day16.patch .    # e.g. from /mnt/c/Users/<you>/Downloads/
git apply --check fbebc-week3-day16.patch && git apply --stat fbebc-week3-day16.patch
git apply fbebc-week3-day16.patch
```

If `--check` fails, paste the output — don't force it. (Fallback: the `.tar.gz`
overwrites the touched files wholesale; only use it if you have no local
changes you want to keep in those files.)

## 2. Verify (unit, then the live Docker suite)

```bash
python -m pytest -q                       # expect: 194 passed
python -m pytest tests/integration -v     # needs Docker; expect 10 passed
```

The integration run also closes the one open item from Day 15:
`test_no_host_secrets_reachable_inside_container` (B08) has never run against
a real daemon.

## 3. Measure real token usage (small, throwaway run)

```bash
export GROQ_API_KEY=...        # never on the command line, never committed
mkdir -p runs
python scripts/run_stage1.py --task circle_packing --conditions single_winner \
    --generations 8 --ledger runs/measure.db --verbose
python scripts/summarize_ledgers.py runs/measure.db
python scripts/usage_report.py --tpd <YOUR_TPD> --rpd <YOUR_RPD> --days 8 --arms 6
```

Read `<YOUR_TPD>` / `<YOUR_RPD>` off your own Groq account's limits page for
`openai/gpt-oss-120b` (console.groq.com/docs/rate-limits or the account
limits page) — do not trust the numbers in `STATUS.md`; free-tier limits move.
`runs/measure.db` is throwaway (pipeline + measurement only, never reported).

This is also the **first live circle_packing generation ever run** — watch for
anything odd (all-`stalled` generations, a huge share of `E_*` rejections, the
baseline not being 2.1667).

The output of step 3 decides the experiment size (target generations per arm)
— see `PREREGISTRATION.md` §2.

### 3b. Prompt v2 pilot (after applying the Day-16 patch 2)

Patch 2 revises Σ's prompt once (`PREREGISTRATION.md` §7). The pilot runs both
conditions round-robin **and** exercises the target/resume driver live. Use a
throwaway seed (9999) so nothing here is confused with the reported arms:

```bash
python scripts/run_stage1.py --task circle_packing \
    --conditions single_winner,elite_band --band-size 3 \
    --seeds 9999 --target-generations 12 --round-size 6 \
    --ledger runs/pilot_v2.db --daily-token-cap 190000 --verbose
# then the IDENTICAL command with a bigger target -- must continue from 12, not restart:
python scripts/run_stage1.py --task circle_packing \
    --conditions single_winner,elite_band --band-size 3 \
    --seeds 9999 --target-generations 20 --round-size 6 \
    --ledger runs/pilot_v2.db --daily-token-cap 190000
python scripts/summarize_ledgers.py runs/pilot_v2.*.db
python scripts/usage_report.py --tpd 200000 --rpd 1000 --days 8 --arms 6 --calls-per-gen 1.3
```

Expected: the second command starts each arm at generation 12; each arm has
exactly one baseline row; ~40 Σ calls (~65K tokens) in total.

## 4. Pre-register and freeze

1. Fill the `[FILL: …]` fields in `PREREGISTRATION.md` (target N, token cap,
   the arithmetic behind N).
2. Commit **everything** — the working tree must be clean at launch so
   `runmeta.json` records `git_dirty: false`:

```bash
git add -A && git commit -m "Week 3 Day 16: matched-arm experiment machinery + pre-registration"
git tag prereg-week3
```

## 5. Launch the matched experiment

Frozen values (`PREREGISTRATION.md` §2): N = 100, token cap 190000.

```bash
python scripts/run_stage1.py --task circle_packing \
    --conditions single_winner,elite_band --band-size 3 \
    --seeds 0,1000,2000 --target-generations 100 --round-size 10 \
    --ledger runs/week3.db --daily-token-cap 190000
```

If today's pilot tokens already count against Groq's window, the first day
may stop early on a real TPD 429 — that is a clean exit (code 3), not a failure;
just re-run tomorrow.

This creates six ledgers — `runs/week3.{single_winner,elite_band}.seed{0,1000,2000}.db`
— each with a `.checkpoint.json`, plus `runs/week3.runmeta.json`.

**Daily routine:** re-run the *identical* command each day. It resumes every
arm from its checkpoint, continues round-robin, and stops (exit code 3) the
moment the provider's budget is hit. Then:

```bash
python scripts/summarize_ledgers.py runs/week3.*.db     # paste this
python scripts/usage_report.py --tpd <TPD> --rpd <RPD>  # tokens/call, drift
```

Things worth a look before leaving it unattended: `outcome=stalled` streaks
(gates rejecting almost everything), a high `E_NO_PROPOSAL` share (Σ not
following the output format), `scored-invalid packings` dominating, or
`ledger chain: FAILED` (stop and investigate — do not `--restart`).

`--restart` archives an arm's ledger and checkpoint (renamed `*.bak-<stamp>`,
never deleted). Use it only deliberately.

Do **not** edit anything under `delta/`, `harness/`, `sigma/` after launch
without logging it in `PREREGISTRATION.md`'s deviation log — the manifest
digest in the ledger would change across the edit.

## 6. Live ADV suite

Covered in step 2 (`tests/integration`, 10 cases); re-run it at the end of
the experiment as well, on the exact code that produced the results.

## 7. What the resume tests do and don't prove

`tests/unit/test_loop_band.py::test_band_resume_reproduces_uninterrupted_run_exactly`
and `test_multiday_matched_run_end_to_end_with_fakes` prove, with fakes, that
interrupt/resume reproduces an uninterrupted run (including which parent the
band sampled each generation) and that the multi-day round-robin driver keeps
arms matched. They do **not** exercise a real Groq 429 or a real
`BudgetExceeded` — the first genuine multi-day run does. If day 2 does not
pick up exactly where day 1 stopped (wrong generation, wrong band, missing
budget message), stop and debug before trusting any numbers.

## 8. End of run

```bash
cp ~/.fbebc_sigma_budget.usage.jsonl runs/week3.usage.jsonl   # total calls/tokens for §5 of the paper
python scripts/summarize_ledgers.py runs/week3.*.db > runs/week3.summary.txt
```

Ledgers are **gitignored** (`*.db`). Archive them separately (a GitHub
release asset or Zenodo deposit) for the public repo — they are the
reproducibility artifact, since Σ is not seeded.
