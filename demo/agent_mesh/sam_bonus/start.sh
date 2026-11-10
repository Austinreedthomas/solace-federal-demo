#!/usr/bin/env bash
# Start the Agent Mesh bonus project: core (orchestrator + web UI + platform)
# and the Operations Watch agent, each in its own process (litellm's async
# client cannot be shared across agent event loops).
cd "$(dirname "$0")/proj" || exit 1
for f in core.pid agent.pid; do
  if [ -f "$f" ] && kill -0 "$(cat "$f")" 2>/dev/null; then
    echo "already running ($f)"
    exit 1
  fi
done
nohup ../.venv/bin/sam run configs/services/platform.yaml configs/gateways/webui.yaml configs/agents/main_orchestrator.yaml > core.log 2>&1 & echo $! > core.pid
nohup ../.venv/bin/sam run configs/agents/ops_watch_agent.yaml > agent.log 2>&1 & echo $! > agent.pid
echo "starting... web UI at http://127.0.0.1:8000 (ready in ~40s)"
