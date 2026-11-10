# Agent Mesh bonus demo

The Publisher and Primary Operator pages run the same Disconnect / guaranteed-send / Connect sequence used in Demo 3. A government customer then asks, in plain English: "What happened overnight to the primary operator? Was anything missed?"

**Operations Watch** is a read-only observer of that existing path. It does not consume from the operator's guaranteed queue and it does not publish. A monitor alongside the agent records when the primary operator disconnects and reconnects, the live depth of its guaranteed queue, and alerts seen on a Direct subscription that does not bind that queue. The Orchestrator hands the question to Operations Watch, which returns the disconnect window, the queued alert ids with ground and type, and a delivery confirmation once the queue has drained to 0.

The Activity panel draws the hand-off: User → OrchestratorAgent → Operations Watch → `get_operator_incident_report`.

Presenter steps: [docs/DEMO-QUICK-REFERENCE.md](../docs/DEMO-QUICK-REFERENCE.md#bonus-agent-mesh-observes-the-primary-operator). Agent files: [agent_mesh/sam_bonus/](agent_mesh/sam_bonus/). Silent review recording (1:33): [MP4](https://github.com/Austinreedthomas/solace-federal-demo/releases/download/demo-videos-20261109/demo4-ops-watch.mp4).

## What you need

- The local Solace broker from [README.md](README.md), with the Publisher and Primary Operator pages already running
- [Solace Agent Mesh](https://docs.solace.com/Agent-Mesh/agent-mesh-home.htm) 1.28.8 in a project virtualenv (Python 3.12)
- A Gemini API key for `gemini-3.8-flash`
- Read-only SEMP access to the local broker so the monitor can see operator bind state and queue depth (the same `SOLACE_OPERATOR_SEMP_*` settings used by the Operators page; see [SPLIT-CLIENT.md](SPLIT-CLIENT.md))

## Install the bonus project

Create an Agent Mesh project directory (any path you choose) with `proj/` for the running project and `.venv/` for the Agent Mesh CLI. Copy the files from `demo/agent_mesh/sam_bonus/` so that:

- `configs/` and `src/` land inside `proj/` (or are referenced the way `start.sh` expects: it `cd`s to `proj/` beside the scripts)
- the scripts `start.sh`, `stop.sh`, `queue-depth.sh`, and `reset-history.sh` sit next to `proj/` and `.venv/`

Set the local broker connection for the agent (VPN `default`, client username `sam-bonus-mesh`, namespace `ssa-bonus-mesh/`, SMF `tcp://localhost:55554` or the SMF port you published). The monitor also reads the operator queue name and SEMP settings from the same env file the Operators page uses (`SOLACE_OPERATOR_QUEUE`, `SOLACE_OPERATOR_SEMP_URL`, and related values). The agent client needs a Direct subscribe permission for `ssa/unclass/>` and, if guaranteed alerts use a separate topic prefix, for that prefix as well.

## Model key

Store the Gemini key as `LLM_SERVICE_API_KEY` in `proj/.env` (mode 600). The same file should set:

```
LLM_SERVICE_ENDPOINT="https://generativelanguage.googleapis.com/v1beta"
LLM_SERVICE_PLANNING_MODEL_NAME="gemini-3.8-flash"
LLM_SERVICE_GENERAL_MODEL_NAME="gemini-3.8-flash"
```

Agent Mesh reads these on first start into `proj/platform.db`. To change the key, edit `.env`, update the corresponding rows in `platform.db`, and restart.

## Start and stop

```sh
./start.sh          # web UI at http://127.0.0.1:8000, ready in about 40 s
./queue-depth.sh    # primary operator queue depth, binds, and subscriptions
./stop.sh
```

Logs: `proj/core.log` (Orchestrator, web UI, platform) and `proj/agent.log` (Operations Watch). History: `proj/data/ops-watch.jsonl`.

Clear history with `./reset-history.sh` while the agent is stopped, then start, before a rerun.

The web UI in `configs/gateways/webui.yaml` runs with `task_logging.enabled: false` and `background_tasks: false` so the chat answer and the Activity diagram stream live.

## Scenario

1. **Agent Mesh → Agents:** the cards **OrchestratorAgent** and **Operations Watch**.
2. Show the primary operator's guaranteed queue at depth 0, with one consumer (`./queue-depth.sh`, or Broker Manager). The operator is connected.
3. **Publisher:** Ground 1 → **Send launch alert** (live baseline; depth stays 0).
4. **Primary Operator:** **Disconnect**. The queue's consumer count goes to 0.
5. **Publisher:** Ground 1 → **Send a guaranteed launch alert** three times. Depth rises by one for each alert that matches the operator queue's subscription. A heartbeat or a Ground 2 launch is queued only if that subscription matches it.
6. **Primary Operator:** **Connect**. The queued alerts arrive tagged **Queued**, and the queue drains to 0.
7. **Agent Mesh → Chat → New Chat**, agent **OrchestratorAgent**. Type the overnight question, then click the send arrow (the Enter key does not send it):
   > What happened overnight to the primary operator? Was anything missed?
8. The answer gives the disconnect window, the queued alert ids with ground and type, and the delivery confirmation that the queue depth is 0.
9. **Activity** panel: User → OrchestratorAgent → Operations Watch → `get_operator_incident_report`, over the local Solace broker.

## Limitations

- This demo runs on the local Solace broker.
- It uses a free-tier Gemini key, so answers take about 20 seconds and heavy use can hit rate limits.
- Event history is a local file. Run `./reset-history.sh` before a rerun, while the agent is stopped.
