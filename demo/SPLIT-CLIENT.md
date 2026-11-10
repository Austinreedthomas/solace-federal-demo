# Two-broker (split client) configuration

By default, `python -m solace_demo web` uses the single local broker in `demo/.env`. Set `SOLACE_SPLIT_CLIENT=1` to open the publisher and operator as two separate Solace clients. This is the path used in the recorded Demos 1–3, where the publisher talks to a Solace Cloud broker and the Primary Operator talks to the local Solace broker.

The pages do not provision or change queues, ACL profiles, or bridges. Certificate checks stay on.

## Environment

Use a file outside the repository, and point the process at it with `SOLACE_DOTENV_PATH`, so Cloud credentials stay out of `demo/.env`:

```bash
SOLACE_DOTENV_PATH=/path/to/split-client.env python -m solace_demo web
```

Include:

```text
SOLACE_SPLIT_CLIENT=1
SOLACE_WEB_PORT=8877
SOLACE_PUBLISHER_HOST=tcps://<cloud-host>:<port>
SOLACE_PUBLISHER_VPN=<vpn>
SOLACE_PUBLISHER_USERNAME=<publisher-client>
SOLACE_PUBLISHER_PASSWORD=<secret>
SOLACE_PUBLISHER_TRUST_STORE=<directory-of-CA-PEMs>
SOLACE_OPERATOR_HOST=tcp://127.0.0.1:55554
SOLACE_OPERATOR_VPN=default
SOLACE_OPERATOR_USERNAME=<operator-client>
SOLACE_OPERATOR_QUEUE=queue-local-operator-guaranteed
SOLACE_GUARANTEED_TOPIC_PREFIX=ssa-guaranteed/unclass
```

Set `SOLACE_OPERATOR_PASSWORD` unless the local broker is configured for no basic authentication (`SOLACE_OPERATOR_AUTH=none` is accepted only for a loopback operator).

A remote publisher host must use `tcps://`. `tcp://` and `http://` are accepted only for `127.0.0.1`, `localhost`, or `::1`. URLs include a port and omit username, password, path, and query. `SOLACE_PUBLISHER_TRUST_STORE` is a directory of trusted CA certificates, passed to the Solace Python API as `SESSION_SSL_TRUST_STORE_DIR`.

For a read-only queue depth while the operator session is down, also set `SOLACE_OPERATOR_SEMP_URL`, `SOLACE_OPERATOR_SEMP_USERNAME`, and `SOLACE_OPERATOR_SEMP_PASSWORD`. The page uses a GET of that queue's message list.

Leave `SOLACE_GUARANTEED_TOPIC_PREFIX` unset for the single-broker lab, where guaranteed alerts stay on `ssa/unclass/...` and `q-ssa-web-console`.

## Broker objects on the two-broker path

Configure these on your brokers before the recorded Demo 3 steps:

- A static bridge, for example `to-cloud-unclass`, initiated from the local Solace broker, with a remote subscription such as `ssa/>` for Direct traffic.
- Cloud queue `queue-cloud-guaranteed` (exclusive) subscribed to `ssa-guaranteed/unclass/>`, consumed by the bridge.
- Local queue `queue-local-operator-guaranteed` (exclusive) subscribed to `ssa-guaranteed/unclass/>`, consumed by the Primary Operator.
- Publisher permission to publish `ssa-guaranteed/unclass/>`.

See [Message VPN Bridges](https://docs.solace.com/Features/VPN/Message-VPN-Bridges.htm). One bridge can carry Direct topic subscriptions and one remote guaranteed queue.

## What the pages show

- A publisher is labeled Solace Cloud when its hostname is a Solace Cloud messaging DNS name; otherwise it is labeled as a remote or local Solace broker.
- The operator page says "Receiving from" while its receiver is up. After **Disconnect**, it reports that the Solace session is still up and that this console is not receiving.
- **Send launch alert** uses the publisher session. The operator card appears when that same alert id is received.
