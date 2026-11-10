#!/usr/bin/env bash
cd "$(dirname "$0")/proj" || exit 1
for f in agent.pid core.pid; do
  [ -f "$f" ] && kill "$(cat "$f")" 2>/dev/null
done
for i in {1..20}; do
  pgrep -f "solace-agent-mesh-demo/.venv/bin/python ../.venv/bin/sam run" >/dev/null || break
  sleep 1
done
if pgrep -f "../.venv/bin/sam run" >/dev/null; then
  echo "still running"
else
  echo "stopped"
fi
rm -f agent.pid core.pid
