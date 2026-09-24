#!/usr/bin/env bash
# scripts/run_week3_until_done.sh -- OPTIONAL convenience: re-run the frozen Week 3
# command until every arm reaches its target, waiting out daily-quota stops.
#
# This only automates "re-run the identical command after the quota resets". It
# adds no capacity: it uses the ONE account/key in GROQ_API_KEY and the same local
# token cap, exactly as running the command by hand each day would.
#
#   export GROQ_API_KEY=...        # then, ideally inside tmux so it survives a closed terminal
#   scripts/run_week3_until_done.sh
#
# Exit code 3 (budget stop: local cap or a real provider 429) -> sleep an hour, retry.
# Retrying is cheap: a locally-capped attempt makes no network call, and a real 429
# costs one request and no tokens. (Each retry appends one record to runmeta.json, so
# expect ~24 "invocations"/day there; that is noise, not a problem.)
# Any other non-zero code (1 integrity/halt, 2 config/ledger-chain, 4 no progress)
# stops the loop: those need a human, not a retry.
set -u
cd "$(dirname "$0")/.."

CMD=(python scripts/run_stage1.py --task circle_packing
     --conditions single_winner,elite_band --band-size 3
     --seeds 0,1000,2000 --target-generations 100 --round-size 10
     --ledger runs/week3.db --daily-token-cap 190000)

while true; do
  "${CMD[@]}"
  code=$?
  case $code in
    0) echo "[$(date -u +%FT%TZ)] all arms reached their target."; exit 0 ;;
    3) echo "[$(date -u +%FT%TZ)] budget stop; retrying in 1 hour."; sleep 3600 ;;
    *) echo "[$(date -u +%FT%TZ)] exit code $code -- stopping; needs a human." >&2; exit "$code" ;;
  esac
done
