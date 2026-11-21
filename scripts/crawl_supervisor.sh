#!/usr/bin/env bash
# Runs the crawl detached from any terminal/chat session, keeps the Mac awake, and auto-resumes
# after crashes. Stops on: finished, budget stop, or MAX_RESTARTS. Logs: data/interim/supervisor.log
set -u
cd "$(dirname "$0")/.."
BUDGET="${BUDGET:-2000}"; MAX_USD="${MAX_USD:-6}"; MAX_RESTARTS="${MAX_RESTARTS:-20}"
LOG=data/interim/supervisor.log; echo $$ > data/interim/supervisor.pid
unset VIRTUAL_ENV
for i in $(seq 1 "$MAX_RESTARTS"); do
  echo "$(date -u +%FT%TZ) start #$i (budget=$BUDGET max_usd=$MAX_USD)" >> "$LOG"
  caffeinate -dimsu uv run cf crawl --budget "$BUDGET" --batch 60 --workers 12 --seed-cap 25 --new-cap 8 \
      --max-usd "$MAX_USD" --resume >> data/interim/crawl_big.log 2>&1
  code=$?
  echo "$(date -u +%FT%TZ) exit code $code" >> "$LOG"
  if python3 -c "import json,sys; d=json.load(open('data/interim/frontier_state.json'))['stats']; sys.exit(0 if d.get('finished') or 'budget' in str(d.get('last_error') or '') else 1)"; then
    echo "$(date -u +%FT%TZ) done (finished or budget stop)" >> "$LOG"; break
  fi
  sleep 15   # brief pause, then resume from the checkpoint
done
rm -f data/interim/supervisor.pid
