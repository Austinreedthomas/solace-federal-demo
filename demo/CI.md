# Broker tests in GitHub Actions

[`.github/workflows/broker-tests.yml`](../.github/workflows/broker-tests.yml) defines two jobs.

## Local software broker

The `local-broker` job runs on every pull request, every push to `main`, and on manual dispatch. It starts `solace/solace-pubsub-standard` at the digest pinned in `docker-compose.yml` (release `10.26.0.9163`). The suite broker's SEMP is `http://127.0.0.1:8080`, SMF is `tcp://127.0.0.1:55555`, and MQTT is `mqtt://127.0.0.1:1883`. The job waits for SEMP, runs `provision`, then runs `pytest` from `demo/` on Python 3.12 with the packages in `requirements.txt` and `requirements-dev.txt`.

Four additional brokers are started with `docker run` so tests that stop or reconfigure a broker leave the suite broker running:

| Container | Host SMF | Host SEMP | Used by |
| --- | --- | --- | --- |
| service `solace` | `55555` | `8080` | The main suite, including the MQTT test |
| `solace-ci-publisher` | `16655` | `18081` | Split-endpoint receipt test (publisher) |
| `solace-ci-operator` | `16755` | `18082` | Split-endpoint receipt test (operator) |
| `solace-ci-noauth` | `16855` | `18083` | Loopback operator with no basic authentication |
| `solace-visual-repro` | `16555` | `18084` | Broker-stop and reconnect test |

The no-auth test changes VPN basic authentication only on `solace-ci-noauth`. The stop test starts and stops only `solace-visual-repro`.

## Solace Cloud job

The `cloud` job runs on pull requests and from **Run workflow**. It runs the permissions tests and, when `SOLACE_CLOUD_MQTT_URL` is set, the MQTT test. If a required secret is empty, the job reports that and does not call the broker.

Create these repository secrets. Values stay in GitHub.

| Secret | What it is |
| --- | --- |
| `SOLACE_CLOUD_HOST` | `tcps://` host and port for the Cloud SMF service |
| `SOLACE_CLOUD_VPN` | Message VPN name |
| `SOLACE_CLOUD_SEMP_URL` | `https://` SEMP base URL for that service |
| `SOLACE_CLOUD_ADMIN_USER` | SEMP username |
| `SOLACE_CLOUD_ADMIN_PASSWORD` | SEMP password |
| `SOLACE_PUBLISHER_USERNAME` | Publisher client username |
| `SOLACE_PUBLISHER_PASSWORD` | Publisher client password |
| `SOLACE_SUBSCRIBER_USERNAME` | Subscriber client username |
| `SOLACE_SUBSCRIBER_PASSWORD` | Subscriber client password |
| `SOLACE_PERMISSIONS_USERNAME` | Restricted client username |
| `SOLACE_PERMISSIONS_PASSWORD` | Restricted client password |
| `SOLACE_PUBLISHER_TRUST_PEM` | PEM text of the Cloud CA used for the publisher |
| `SOLACE_PERMISSIONS_TRUST_PEM` | PEM text of the Cloud CA used for the restricted client |
| `SOLACE_CLOUD_MQTT_URL` | Optional `mqtts://` URL. When empty, the MQTT cloud test is skipped |

The job splits each trust PEM into one certificate per file for `SOLACE_PUBLISHER_TRUST_STORE` and `SOLACE_PERMISSIONS_TRUST_STORE`. `SOLACE_MQTT_TRUST_FILE` is the publisher chain as a single PEM.

The permissions tests may create a disposable `perm-demo-user` on the named VPN. On a remote broker, `provision()` leaves the configured publisher and subscriber usernames, their profiles, and their passwords unchanged. The job's last step reads both usernames with SEMP GET and fails if either client or ACL profile is no longer `default`. Create the subscriber client on the VPN before the first Cloud run, with permission to connect and to subscribe to the demo topics those tests use.
