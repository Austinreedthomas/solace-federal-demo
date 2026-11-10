#!/usr/bin/env bash
# Clear persisted Operations Watch history so the next start has a clean record.
# Does not change the broker or the operator queue. Run only when the agent is stopped.
set -euo pipefail
cd "$(dirname "$0")/proj" || exit 1
if [ -f agent.pid ] && kill -0 "$(cat agent.pid)" 2>/dev/null; then
  echo "stop the Operations Watch agent first (./stop.sh)"
  exit 1
fi
rm -f data/ops-watch.jsonl data/ops-watch-state.json data/ops-watch-state.tmp
echo "event history cleared"
