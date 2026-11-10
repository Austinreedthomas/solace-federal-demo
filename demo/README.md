# Demo lab

A local Solace Standard software broker, command-line scenarios, and browser pages for the satellite-alert example. The default lab is a single broker on loopback, Message VPN `default`.

The presentation lives under `presentation/` and is unchanged by this lab.

## Prerequisites

- Python 3.9 or newer
- Docker
- The packages in `requirements.txt` (`solace-pubsubplus` 1.11.0 and `paho-mqtt` 2.1.0)

The pinned broker image is `solace/solace-pubsub-standard` digest `sha256:4891915f6882a8329ad662ff6638cb6ea14e4603447f2fd26e73f10e4adc55af` (release `10.26.0.9163`). Messaging uses SMF, so subscriptions use Solace `*` and `>` wildcards.

## Quick start

```bash
cd demo
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and replace every `CHANGE_ME` password. Keep `SOLACE_HOST` and `SOLACE_SEMP_URL` on loopback. If host ports 8080 or 55554 are already in use, set `SOLACE_SEMP_PORT` and `SOLACE_SMF_PORT` to free ports and use the same numbers in `SOLACE_SEMP_URL` and `SOLACE_HOST`.

`docker compose` reads `.env` for the published ports. The Python commands read that same file themselves; there is no need to `source` it.

```bash
docker compose -p solace-ssa-demo up -d
python -m solace_demo prereqs
python -m solace_demo wait
python -m solace_demo quickstart
```

`python -m solace_demo config-check` prints the host, SEMP URL, VPN, and whether each password key is set.

The admin password is applied the first time the `solace-ssa-demo-storage` volume is created. If `wait` returns SEMP 401 after a first start that still had the placeholder password, run `python -m solace_demo sync-admin-password`, then run `wait` again.

## Web pages

```bash
python -m solace_demo web
```

Open:

- http://127.0.0.1:8877/publisher
- http://127.0.0.1:8877/operator
- http://127.0.0.1:8877/restricted-operator

The server binds to `127.0.0.1`. Set `SOLACE_WEB_PORT` if 8877 is taken, and `SOLACE_WEB_HOST` if you need a different bind address. Broker Manager is http://127.0.0.1:8080 (or your `SOLACE_SEMP_PORT`).

`SOLACE_WEB_ROLE` selects the pages in one process: `all` (default) serves every page; `publisher` serves `/publisher`; `operators` serves `/operator` and `/restricted-operator`.

On this local lab, a Ground 1 guaranteed alert sent while the operator is disconnected stays on queue `q-ssa-web-console`. After Connect it appears on **Ground 1 · object 25544**, tagged Queued. A direct alert sent while disconnected is not recovered.

Click-by-click walkthroughs, including the recorded demos, are in [../docs/DEMO-QUICK-REFERENCE.md](../docs/DEMO-QUICK-REFERENCE.md).

## Command-line scenarios

`quickstart` runs these in order and prints a short architecture note before each step:

```bash
python -m solace_demo routing
python -m solace_demo access
python -m solace_demo delivery
```

1. **Routing.** A publisher sends three example messages. Subscription `ssa/unclass/*/launch/>` receives launch events from any site. Subscription `ssa/unclass/ground1/*/25544/>` receives every event for object `25544` at Ground 1, including a status heartbeat that the launch subscription misses.
2. **Access.** The publisher profile may publish on `ssa/unclass/>` and is denied on `admin/test/>`. The subscriber profile is the reverse. An allowed launch alert is received. Queue bind permission for `q-ssa-operator` is configured separately.
3. **Delivery.** While the direct subscriber is offline, a direct message is not recovered later. A guaranteed alert stays on `q-ssa-operator` until the owner binds and acknowledges it.

`delivery` and `quickstart` recreate `q-ssa-operator` before the guaranteed message so a rerun starts clean. `python -m solace_demo reset` does that recreate by itself.

## Configuration

See [`.env.example`](.env.example) for every supported variable.

- **Local lab:** `SOLACE_HOST`, `SOLACE_SEMP_URL`, `SOLACE_VPN`, and the admin, publisher, and subscriber passwords.
- **Two-broker path:** set `SOLACE_SPLIT_CLIENT=1` and the `SOLACE_PUBLISHER_*` / `SOLACE_OPERATOR_*` variables in a separate env file. See [SPLIT-CLIENT.md](SPLIT-CLIENT.md).
- **Restricted client:** set `SOLACE_PERMISSIONS_DEMO=1` and the permissions credentials. See [PERMISSIONS-DEMO.md](PERMISSIONS-DEMO.md).
- **Simulated weather (MQTT):** set `SOLACE_MQTT_WEATHER=1`. See [MQTT-WEATHER.md](MQTT-WEATHER.md).

To keep Cloud credentials out of the local-lab `.env`, point the process at another file:

```bash
SOLACE_DOTENV_PATH=/path/to/split-client.env python -m solace_demo web
```

An example systemd unit for running only the publisher page on a host on your network is in [../deploy/vm-publisher/](../deploy/vm-publisher/).

## Bonus: Agent Mesh

Operations Watch observes the primary operator and its guaranteed queue, and can report which alerts waited while the operator was disconnected. See [AGENT-MESH.md](AGENT-MESH.md) and the [Quick Reference](../docs/DEMO-QUICK-REFERENCE.md#bonus-agent-mesh-observes-the-primary-operator).

## Tests

```bash
python -m pip install -r requirements-dev.txt
python -m pytest
```

Most tests run without a broker. Broker integration tests run when the lab is up and the passwords in `.env` are set. CI is described in [CI.md](CI.md).

## Stop the lab

```bash
docker compose -p solace-ssa-demo down
```

Add `-v` only if you also want to delete the `solace-ssa-demo-storage` volume.

## Demo videos

Recorded walkthroughs are on the [v1.0](https://github.com/Austinreedthomas/solace-federal-demo/releases/tag/v1.0) GitHub Release.

| Demo | Purpose | Length | Video | Steps |
| --- | --- | --- | --- | --- |
| Demo 1 — Topic routing and live (Direct) delivery | One publish reaches every application whose interest matches. | 2:53 | [MP4](https://github.com/Austinreedthomas/solace-federal-demo/releases/download/v1.0/demo1-topic-routing-and-direct.mp4) | [Steps](../docs/DEMO-QUICK-REFERENCE.md#demo-1-topic-routing-and-live-direct-delivery) |
| Demo 2 — Restricted client permissions | The Solace Cloud broker decides what a signed-in client may publish and subscribe to. | 2:21 | [MP4](https://github.com/Austinreedthomas/solace-federal-demo/releases/download/v1.0/demo2-restricted-client-permissions.mp4) | [Steps](../docs/DEMO-QUICK-REFERENCE.md#demo-2-restricted-client-permissions) |
| Demo 3 — Guaranteed delivery from a Solace Cloud broker to the local Solace broker | A Guaranteed alert waits in the queue on the local Solace broker while the operator is paused, then arrives tagged Queued when receiving resumes. | 2:26 | [MP4](https://github.com/Austinreedthomas/solace-federal-demo/releases/download/v1.0/demo3-guaranteed-offline-recovery.mp4) | [Steps](../docs/DEMO-QUICK-REFERENCE.md#demo-3-guaranteed-delivery-from-a-solace-cloud-broker-to-the-local-solace-broker) |
| Bonus — Agent Mesh observes the primary operator | Operations Watch reports which guaranteed alerts queued while the primary operator was disconnected, and confirms delivery after reconnect. | 1:33 | [MP4](https://github.com/Austinreedthomas/solace-federal-demo/releases/download/v1.0/demo4-ops-watch.mp4) | [Steps](../docs/DEMO-QUICK-REFERENCE.md#bonus-agent-mesh-observes-the-primary-operator) |
