# Solace Demo Quick Reference

Four short demos. Each one has a purpose, a setup check, steps to perform, and what the viewer sees as broker evidence. Start the lab as described in [demo/README.md](../demo/README.md).

## Setup at a glance

- **Publisher:** http://127.0.0.1:8877/publisher (or the host and `SOLACE_WEB_PORT` you configured). In the two-broker path this page publishes to the Solace Cloud broker.
- **Primary Operator:** http://127.0.0.1:8877/operator. Connects to the local Solace broker.
- **Restricted Operator:** http://127.0.0.1:8877/restricted-operator. In the two-broker path this page uses the restricted Solace Cloud client.
- **Local Solace broker:** Broker Manager is http://127.0.0.1:8080 (or your `SOLACE_SEMP_PORT`).
- **Bridge to-cloud-unclass** (two-broker path): carries alerts from the Solace Cloud broker to the local Solace broker.

The Ground selector on the Publisher sets the site for **Send launch alert**, **Send heartbeat**, **Send a direct alert**, and **Send a guaranteed launch alert**. The Ground 1 card shows Ground 1 alerts for object 25544.

Connection hosts, protocols, and logins are listed in [Connections](../README.md#connections). Topics follow the six-level structure described in [Topic structure](../README.md#topic-structure).

## Pre-demo checklist

- The local Solace broker is running and `python -m solace_demo web` is serving the pages.
- For the two-broker recordings, the static bridge shows Incoming Up and the Publisher is connected to Solace Cloud. See [demo/SPLIT-CLIENT.md](../demo/SPLIT-CLIENT.md).
- Start a fresh browser session so the pages show new receipts.
- On the Primary Operator page, click **Clear** on both cards so each starts empty, and confirm the header shows **Queue holding 0**.

## Demo 1: Topic routing and live (Direct) delivery

**Purpose:** One publish reaches every application whose interest matches. The sender publishes the event on a topic.

**Setup**

- The Primary Operator page is connected to the local Solace broker and receiving.
- Broker Manager is open to the Primary Operator client's subscriptions.

**Steps**

1. In Broker Manager, show the operator's two subscriptions: `ssa/unclass/*/launch/>` (launches from any site) and `ssa/unclass/ground1/*/25544/>` (every event about object 25544 at Ground 1).
2. On the Publisher page, choose **Ground 1**, click **Send launch alert**. The same new id appears in **Any site · launch alerts** and in **Ground 1 · object 25544**, tagged Direct, on topic `ssa/unclass/ground1/launch/25544/alert`.
3. Choose **Ground 2**, click **Send launch alert**. The new id appears in **Any site · launch alerts** on topic `ssa/unclass/ground2/launch/25544/alert`. The Ground 1 card still shows the Ground 1 launch id.
4. Choose **Ground 1**, click **Send heartbeat**. The new id appears in **Ground 1 · object 25544**, tagged Direct, on topic `ssa/unclass/ground1/status/25544/heartbeat`.
5. Choose **Ground 2**, click **Send heartbeat**. The operator cards continue to show the Ground 2 launch and the Ground 1 heartbeat.
6. Choose **Ground 1**. On the Primary Operator page, click **Disconnect**. The Publisher stays connected. The header reads: “Not receiving. The Solace session to Solace broker is still up.”
7. Click **Send a direct alert**. The Publisher reports Sent, on topic `ssa/unclass/ground1/live/25544/update`.
8. Click **Connect**. The header returns to Receiving from the local Solace broker.
9. Click **Send a direct alert** again. The new id arrives in **Ground 1 · object 25544**, tagged Direct, on topic `ssa/unclass/ground1/live/25544/update`.

**Why it matters:** One shared topic contract serves different interests. Another application can add its own interest. Direct suits a fresh update. An alert that must wait uses Guaranteed delivery (Demo 3).

## Demo 2: Restricted client permissions

**Purpose:** The Solace Cloud broker decides what a signed-in client may publish and subscribe to. The application sends the request.

**Setup**

- Broker Manager is open on the Solace Cloud broker.
- The Restricted Operator page is open, with all three results showing "Not started."
- The restricted client is enabled as in [demo/PERMISSIONS-DEMO.md](../demo/PERMISSIONS-DEMO.md).

**Steps**

1. In Broker Manager, show client **client-cloud-permissions-demo**: enabled, assigned ACL profile **acl-cloud-permissions-demo**.
2. Open the ACL Profiles list. For **acl-cloud-permissions-demo**, Client Connect default action is Allow, Publish default action is Disallow, and Subscribe default action is Disallow.
3. Open the profile's **Client Connect** tab. Client Connect Default Action is Allow.
4. Open **Publish Topic**: Publish Default Action is Disallow, with one exception, `solace-demo/permissions/allowed/>`.
5. Open **Subscribe Topic**: Subscribe Default Action is Disallow, with the same exception.
6. On the Restricted Operator page, click **Subscribe and send one**. The green result reads: This client received its own message. Sent ID matches Received ID on topic `solace-demo/permissions/allowed/proof`.
7. Click **Request the forbidden subscription**. The red result reads: Broker refused this subscription, on topic `solace-demo/permissions/denied/proof`, with **Subscription ACL Denied**.
8. Click **Try to publish to a forbidden topic**. The red result reads: Broker refused this publish, on topic `solace-demo/permissions/denied/proof`.

Hold on the page so all three results are visible together.

**Why it matters:** The rule lives on the broker. The page sends the request, and the broker enforces the authenticated client's topic permissions. The allowed path is shown first with the same identity. A refusal comes back as the broker's response.

## Demo 3: Guaranteed delivery from a Solace Cloud broker to the local Solace broker

**Purpose:** A Guaranteed alert waits in the queue on the local Solace broker while the operator's receiving is paused, then arrives tagged Queued when receiving resumes.

**Setup**

- Broker Manager is open on the Solace Cloud broker and on the local Solace broker.
- The Primary Operator page is connected and receiving.
- The Publisher Ground selector is **Ground 1**, so the guaranteed topic is `ssa-guaranteed/unclass/ground1/launch/25544/alert` and the Ground 1 card is the card that shows it.

**Steps**

1. In Broker Manager on the Solace Cloud broker, show queue `queue-cloud-guaranteed`: Messages Queued is 0, Current Consumers is 1. The Subscriptions tab shows `ssa-guaranteed/unclass/>`.
2. Open the Consumers tab. One consumer: the bridge `#bridge/remote/to-cloud-unclass/…`.
3. On the local Solace broker, show the bridge to-cloud-unclass: Incoming Up. The remote queue name is `queue-cloud-guaranteed`.
4. Show queue `queue-local-operator-guaranteed`: Messages Queued is 0, Current Consumers is 1.
5. On the Primary Operator page, click **Disconnect**. The header reads: “Not receiving. The Solace session to Solace broker is still up.”
6. Refresh the queue view on the local Solace broker. Messages Queued is 0, Current Consumers is 0.
7. On the Publisher page, with **Ground 1** selected, click **Send a guaranteed launch alert**. The broker acknowledged the alert, on topic `ssa-guaranteed/unclass/ground1/launch/25544/alert`.
8. Refresh the queue view on the local Solace broker. Messages Queued is 1, Current Consumers is 0.
9. On the Primary Operator page, click **Connect**. Receiving from the local Solace broker resumes. The same alert id appears in **Ground 1 · object 25544**, tagged **Queued**, with "Already on this console's queue."
10. Refresh the queue view. Messages Queued is 0, Current Consumers is 1.

**Why it matters:** Broker acceptance and operator receipt are separate, visible events. The publisher gets a broker acknowledgement. The operator receives the alert when receiving resumes. The alert crosses the bridge from the Solace Cloud broker to the local Solace broker and waits on the queue until the operator is receiving.

## Bonus: Agent Mesh observes the primary operator

<a id="bonus-agent-mesh-observes-the-primary-operator"></a>
<a id="bonus-agent-mesh-outage-and-recovery"></a>

Silent review recording (1:33): [MP4](https://github.com/Austinreedthomas/solace-federal-demo/releases/download/v1.0/demo4-ops-watch.mp4).

**Purpose:** After the same Disconnect / guaranteed-send / Connect sequence used in Demo 3, a government customer asks, in plain English, what happened overnight to the primary operator and whether anything was missed. Operations Watch answers from a read-only view of that operator's disconnect window and guaranteed queue.

The agent is an observer. It does not replace the operator, it does not consume from the operator's queue, and the demo uses the same Publisher and Operators buttons as Demos 1–3.

**Setup**

- The local Solace broker is running. Broker Manager is http://127.0.0.1:8080 (or your SEMP port).
- Publisher and Primary Operator pages are open, as in Demo 3. The primary operator is connected, and its guaranteed queue is at depth 0.
- Agent Mesh is running from its project directory (`./start.sh`). The web UI is http://127.0.0.1:8000. See [demo/AGENT-MESH.md](../demo/AGENT-MESH.md).

**Steps**

1. Open http://127.0.0.1:8000 and the **Agents** view. The cards are **OrchestratorAgent** and **Operations Watch**.
2. In Broker Manager, or with `./queue-depth.sh` from the Agent Mesh project directory, show the primary operator's guaranteed queue (the queue name also appears on the Operators page): Messages Queued is 0, Current Consumers is 1.
3. On the Publisher page, with **Ground 1** selected, click **Send launch alert**. This is the live (Direct) baseline; the operator queue stays at 0.
4. On the Primary Operator page, click **Disconnect**. Current Consumers on the queue goes to 0.
5. On the Publisher page, with **Ground 1** selected, click **Send a guaranteed launch alert** three times. Optionally also send a Ground 1 heartbeat and a Ground 2 launch or guaranteed launch; those land on this operator's queue only if its subscription matches them.
6. Refresh the queue view. Messages Queued equals the number of matching guaranteed alerts (typically 3 when three Ground 1 guaranteed launches were sent). Current Consumers is 0.
7. On the Primary Operator page, click **Connect**. Receiving resumes. Matching alerts appear tagged **Queued**. Refresh the queue view: Messages Queued is 0, Current Consumers is 1.
8. In Agent Mesh, open **Chat**, click **New Chat**, and choose **OrchestratorAgent**. Type:

    > What happened overnight to the primary operator? Was anything missed?

    Click the send arrow to send the question. The Enter key does not send it.
9. Open **Activity**. The hand-off is OrchestratorAgent → Operations Watch → `get_operator_incident_report`, over the local Solace broker.
10. Read the answer: the disconnect window, the queued alert ids with ground and type, and the delivery confirmation that the queue depth is 0 and the counts match.

**Why it matters:** The same durable queue that holds alerts for a disconnected operator can be observed, without consuming those alerts, so an agent can explain what waited and confirm delivery after reconnect. Core routing, access, and delivery still stand on their own; Agent Mesh is an advisory layer on top.

**To rerun**

1. Confirm the primary operator is connected and its queue depth is 0.
2. Stop Agent Mesh with `./stop.sh`, run `./reset-history.sh` to clear the local event history, then `./start.sh`.
3. Begin again from the Agents view and a queue depth of 0.

**Limitations**

- This demo runs on the local Solace broker.
- It uses a free-tier Gemini key, so answers take about 20 seconds and heavy use can hit rate limits.
- Event history is a local file. Run `./reset-history.sh` before a rerun, while the agent is stopped.

## Tying it together

Routing decides who receives an event, permissions decide who is allowed to, and the delivery mode decides whether it waits. The bonus Agent Mesh demo watches that same guaranteed path for the primary operator and reports what queued while the operator was disconnected, then confirms delivery after reconnect.

## After the demo

- Stop the web process with Ctrl+C.
- Run `docker compose -p solace-ssa-demo down` to stop the local lab broker.
- If you ran the bonus Agent Mesh demo, run `./stop.sh` from the Agent Mesh project directory.
