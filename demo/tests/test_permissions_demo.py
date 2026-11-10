"""The permissions CLI prints broker results and does not invent a denial."""

import json
import logging
import os

import pytest

import permissions_demo
from permissions_demo import (
    PUBLISH_DENIAL,
    SUBSCRIBE_DENIAL,
    load_credentials,
    parse_args,
    run,
    sanitize,
    tls_configuration,
)


def test_each_command_requires_the_typed_client_and_topic():
    args = parse_args(["subscribe", "--client", "client-cloud-permissions-demo", "--topic", "solace-demo/permissions/denied/proof"])
    assert args.action == "subscribe"
    assert args.client == "client-cloud-permissions-demo"
    with pytest.raises(SystemExit):
        parse_args(["allowed-send", "--topic", "solace-demo/permissions/allowed/proof"])


def test_username_must_match_the_typed_client(tmp_path, monkeypatch):
    path = tmp_path / "client.json"
    path.write_text(json.dumps({
        "host": "tcps://example.invalid:55443",
        "password": "secret-value",
        "username": "someone-else",
        "vpn": "ground-station",
    }), encoding="utf-8")
    monkeypatch.setenv("SOLACE_PERMISSIONS_CONFIG", str(path))
    monkeypatch.setenv("SOLACE_PERMISSIONS_EVIDENCE_DIR", str(tmp_path / "evidence"))
    code = run(["allowed-send", "--client", "client-cloud-permissions-demo", "--topic", "solace-demo/permissions/allowed/proof"])
    assert code == 1
    text = "\n".join(p.read_text(encoding="utf-8") for p in (tmp_path / "evidence").iterdir())
    assert "does not match --client" in text
    assert "secret-value" not in text
    assert "example.invalid" not in text


def test_control_character_in_the_url_is_not_echoed(tmp_path, monkeypatch):
    path = tmp_path / "client.json"
    path.write_text(json.dumps({
        "host": "tcps://example.invalid\n:55443",
        "password": "secret-value",
        "username": "client-cloud-permissions-demo",
        "vpn": "ground-station",
    }), encoding="utf-8")
    monkeypatch.setenv("SOLACE_PERMISSIONS_CONFIG", str(path))
    monkeypatch.setenv("SOLACE_PERMISSIONS_EVIDENCE_DIR", str(tmp_path / "evidence"))
    assert run(["subscribe", "--client", "client-cloud-permissions-demo", "--topic", "solace-demo/permissions/denied/proof"]) == 1
    text = "\n".join(p.read_text() for p in (tmp_path / "evidence").iterdir())
    assert "\n:55443" not in text
    assert "secret-value" not in text


def test_tls_keeps_certificate_and_hostname_checks(tmp_path):
    checked = tls_configuration(tmp_path)
    assert checked["solace.messaging.tls.cert-validated"] is True
    assert checked["solace.messaging.tls.cert-validate-servername"] is True
    assert checked["solace.messaging.tls.cert-reject-expired"] is True


def test_a_denial_is_only_the_sdk_subcode():
    class Boom(Exception):
        pass

    text = permissions_demo.sdk_text(Boom("something else"))
    assert SUBSCRIBE_DENIAL not in text
    assert PUBLISH_DENIAL not in text
    assert "403" not in text
    redacted = sanitize("host=tcps://broker.example:55443 password=secret-value", ["secret-value", "tcps://broker.example:55443", "broker.example"])
    assert "secret-value" not in redacted
    assert "broker.example" not in redacted


def test_evidence_files_do_not_replace_each_other(tmp_path, monkeypatch):
    monkeypatch.setenv("SOLACE_PERMISSIONS_EVIDENCE_DIR", str(tmp_path))
    first = permissions_demo.evidence_file("subscribe")
    second = permissions_demo.evidence_file("subscribe")
    assert first != second
    assert first.exists() and second.exists()


def test_loopback_plaintext_is_refused_without_the_test_switch(tmp_path, monkeypatch):
    path = tmp_path / "client.json"
    path.write_text(json.dumps({
        "host": "tcp://127.0.0.1:15555",
        "password": "secret-value",
        "username": "client-cloud-permissions-demo",
        "vpn": "default",
    }), encoding="utf-8")
    monkeypatch.setenv("SOLACE_PERMISSIONS_CONFIG", str(path))
    monkeypatch.delenv("SOLACE_PERMISSIONS_ALLOW_LOOPBACK", raising=False)
    with pytest.raises(permissions_demo.DemoFailure) as raised:
        load_credentials(path)
    assert "secret-value" not in " ".join(raised.value.lines)


def test_receipt_lines_use_the_message_that_arrived():
    class Arrived:
        def get_destination_name(self):
            return "solace-demo/permissions/allowed/proof"

        def get_correlation_id(self):
            return "perm-from-the-message"

        def get_payload_as_string(self):
            return ""

    lines = permissions_demo.receipt_lines(
        "perm-from-the-message", Arrived(), "solace-demo/permissions/allowed/proof"
    )
    assert "sent_id=perm-from-the-message" in lines
    assert "received_id=perm-from-the-message" in lines
    assert "received_topic=solace-demo/permissions/allowed/proof" in lines
    assert "result=received" in lines

    class Different:
        def get_destination_name(self):
            return "arrived/on/another/topic"

        def get_correlation_id(self):
            return "perm-other"

        def get_payload_as_string(self):
            return ""

    mismatch = permissions_demo.receipt_lines("perm-sent", Different(), "solace-demo/permissions/allowed/proof")
    assert "sent_id=perm-sent" in mismatch
    assert "received_id=perm-other" in mismatch
    assert "received_topic=arrived/on/another/topic" in mismatch
    assert "result=received" not in mismatch


def test_unexpected_connect_error_is_sanitized(tmp_path, monkeypatch, capsys):
    path = tmp_path / "client.json"
    path.write_text(json.dumps({
        "host": "tcps://secret-host.example:55443",
        "password": "secret-value",
        "username": "client-cloud-permissions-demo",
        "vpn": "ground-station",
    }), encoding="utf-8")
    trust = tmp_path / "trusted-ca"
    trust.mkdir()
    monkeypatch.setenv("SOLACE_PERMISSIONS_CONFIG", str(path))
    monkeypatch.setenv("SOLACE_PERMISSIONS_TRUST_STORE", str(trust))
    monkeypatch.setenv("SOLACE_PERMISSIONS_EVIDENCE_DIR", str(tmp_path / "evidence"))

    def boom(_creds):
        logging.getLogger("solace.messaging.receiver").warning(
            "Unable to unsubscribe from topic tcps://secret-host.example:55443 secret-value"
        )
        os.write(2, b"Unable to unsubscribe from topic tcps://secret-host.example:55443 secret-value\n")
        raise RuntimeError("connect failed at tcps://secret-host.example:55443 with secret-value")

    monkeypatch.setattr(permissions_demo, "connect_service", boom)
    code = run([
        "allowed-send",
        "--client", "client-cloud-permissions-demo",
        "--topic", "solace-demo/permissions/allowed/proof",
    ])
    captured = capsys.readouterr()
    assert code == 1
    assert "Traceback" not in captured.out
    assert "Traceback" not in captured.err
    assert "unsubscribe" not in captured.out.lower()
    assert "unsubscribe" not in captured.err.lower()
    assert "secret-value" not in captured.out
    assert "secret-host.example" not in captured.out
    assert captured.out.startswith("actor=")
    assert "result=failed" in captured.out
    assert "sdk=" in captured.out
    assert "connection=verified" not in captured.out
    stored = "\n".join(item.read_text(encoding="utf-8") for item in (tmp_path / "evidence").iterdir())
    assert "secret-value" not in stored
    assert "secret-host.example" not in stored


def test_policy_label_is_the_prefix_not_the_example_topic(monkeypatch, tmp_path):
    from pathlib import Path

    from solace_demo.topics import subscription_matches

    page = Path(__file__).resolve().parents[1].joinpath("web", "restricted-operator.html").read_text(encoding="utf-8")
    assert "denied except " not in page
    assert "permissionsPolicyNote" in page
    path = tmp_path / "client.json"
    path.write_text(json.dumps({
        "host": "tcp://127.0.0.1:9",
        "password": "secret-value",
        "username": "client-cloud-permissions-demo",
        "vpn": "default",
    }), encoding="utf-8")
    monkeypatch.setenv("SOLACE_PERMISSIONS_DEMO", "1")
    monkeypatch.setenv("SOLACE_PERMISSIONS_ALLOW_LOOPBACK", "1")
    monkeypatch.setenv("SOLACE_PERMISSIONS_CONFIG", str(path))
    status = permissions_demo.permissions_status()
    note = status["permissionsPolicyNote"]
    assert "Connect is allowed" in note
    assert "not a live ACL read" not in note
    assert status["permissionsAllowPrefix"] == "solace-demo/permissions/allowed/>"
    assert "solace-demo/permissions/allowed/>" in note
    assert note.endswith(".")
    assert status["permissionsAllowedTopic"] == "solace-demo/permissions/allowed/proof"
    assert "solace-demo/permissions/allowed/proof" not in note
    assert "denied except solace-demo/permissions/allowed/proof" not in note
    assert subscription_matches(status["permissionsAllowPrefix"], status["permissionsAllowedTopic"])
    assert subscription_matches(status["permissionsAllowPrefix"], "solace-demo/permissions/allowed/another")
    assert not subscription_matches(status["permissionsAllowPrefix"], status["permissionsDeniedTopic"])


def test_policy_note_survives_state_sanitization(monkeypatch, tmp_path):
    from solace_demo.config import LabConfig
    from solace_demo.web import public_payload

    path = tmp_path / "client.json"
    path.write_text(json.dumps({
        "host": "tcps://broker.example:55443",
        "password": "secret-value",
        "username": "client-cloud-permissions-demo",
        "vpn": "ground-station",
    }), encoding="utf-8")
    monkeypatch.setenv("SOLACE_PERMISSIONS_DEMO", "1")
    monkeypatch.setenv("SOLACE_PERMISSIONS_ALLOW_LOOPBACK", "1")
    monkeypatch.setenv("SOLACE_PERMISSIONS_CONFIG", str(path))
    status = permissions_demo.permissions_status()
    note = status["permissionsPolicyNote"]
    config = LabConfig(
        host="tcp://127.0.0.1:16555",
        vpn="default",
        semp_url="http://127.0.0.1:19081",
        admin_user="admin",
        admin_password="local-admin-secret",
        publisher_username="ssa-publisher",
        publisher_password="publisher-secret",
        subscriber_username="ssa-subscriber",
        subscriber_password="subscriber-secret",
        allow_remote=False,
    )
    cleaned = public_payload(dict(status), config, tuple(permissions_demo.permission_secret_values()))
    shown = cleaned["permissionsPolicyNote"]
    assert shown == note
    assert shown == (
        "Connect is allowed. Publish and subscribe are allowed on solace-demo/permissions/allowed/> "
        "and denied on other topics."
    )
    assert shown.endswith(".")
    assert "solace-demo/permissions/allowed/>" in shown
    assert len(shown) <= 240
    assert "[redacted]" not in shown
    assert "secret-value" not in str(cleaned)
    assert "tcps://broker.example:55443" not in str(cleaned)


def test_publish_button_names_the_attempt_not_the_delivery_mode():
    import re
    from pathlib import Path

    page = Path(__file__).resolve().parents[1].joinpath("web", "restricted-operator.html").read_text(encoding="utf-8")
    publisher = Path(__file__).resolve().parents[1].joinpath("web", "publisher.html").read_text(encoding="utf-8")
    assert ">Try to publish to a forbidden topic</button>" in page
    assert "Send one guaranteed message" not in page
    assert 'permissionsClick("publish-guaranteed"' in page
    assert "/api/send" not in page
    assert "/api/listen" not in page
    visible = re.sub(r"<script>.*?</script>", "", page, flags=re.S)
    visible = re.sub(r"<details>.*?</details>", "", visible, flags=re.S)
    assert "guaranteed" not in visible.lower()
    script = re.search(r"<script>(.*)</script>", page, flags=re.S).group(1)
    assert "guaranteed" not in script.replace("publish-guaranteed", "").lower()
    assert "payload.connectionVerified === true" in script
    assert ">Not connected</p>" in page
    assert "perm-allow" not in publisher
    assert "Try to publish to a forbidden topic" not in publisher
    assert "broker should refuse" not in publisher
    assert "Server returned " in publisher


def test_recording_pages_drop_disclaimer_clutter():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    publisher = (root / "web" / "publisher.html").read_text(encoding="utf-8")
    operator = (root / "web" / "operator.html").read_text(encoding="utf-8")
    restricted = (root / "web" / "restricted-operator.html").read_text(encoding="utf-8")
    readme = (root / "README.md").read_text(encoding="utf-8")
    for page in (publisher, operator, restricted):
        assert "Example · unclassified scenario" not in page
        assert "Not Kafka" not in page
    assert "Publisher client " not in publisher
    assert "This window sends through its Solace session only." not in publisher
    assert "simulated, not a sensor" not in publisher
    assert "to-cloud-unclass" in publisher
    assert "Bridge to-cloud-unclass carries alerts to the operator broker." in publisher
    assert "does not report" not in publisher
    assert "Operator authentication: none" not in operator
    assert "Not an ACL or identity proof" not in operator
    assert "this computer" not in operator.lower()
    assert "127.0.0.1" not in operator
    assert "Configured sessions" not in operator
    assert "primaryOperatorPath" not in operator
    assert "operatorBrokerLabel" in operator
    assert "Receiving from " in operator
    assert "Primary Operator" in operator
    assert "Client " in operator
    assert "path to the local broker" not in publisher
    assert ">Try to publish to a forbidden topic</button>" in restricted
    assert "Same computer" not in restricted
    assert "this computer" not in restricted.lower()
    assert "permissionsBrokerLabel" in restricted
    assert "docker compose -p solace-ssa-demo" in readme
    assert "http://127.0.0.1:8080" in readme
    assert "SOLACE_WEB_ROLE" in readme
    assert "launch-web-permissions.sh" not in readme
    assert "docker start ground-station" not in readme
    assert "deploy/vm-publisher" in readme
    assert "/publisher" in readme and "/operator" in readme and "/restricted-operator" in readme
    assert "SPLIT-CLIENT.md" in readme


def test_connection_verified_requires_the_sdk_session(tmp_path, monkeypatch):
    path = tmp_path / "client.json"
    path.write_text(json.dumps({
        "host": "tcps://broker.example:55443",
        "password": "secret-value",
        "username": "client-cloud-permissions-demo",
        "vpn": "ground-station",
    }), encoding="utf-8")
    monkeypatch.setenv("SOLACE_PERMISSIONS_DEMO", "1")
    monkeypatch.setenv("SOLACE_PERMISSIONS_CONFIG", str(path))
    status = permissions_demo.permissions_status()
    assert status["permissionsReady"] is True
    assert "connectionVerified" not in status

    class Session:
        def __init__(self, up):
            self.is_connected = up

        def disconnect(self):
            self.is_connected = False

    calls = {"n": 0}

    def allowed(service, topic):
        calls["n"] += 1
        assert service.is_connected is True
        return [
            "sent_id=perm-1",
            "received_id=perm-1",
            "received_topic=" + topic,
            "result=received",
            "send_returned=yes",
            "broker_ack=yes",
        ]

    up = Session(True)
    monkeypatch.setattr(permissions_demo, "connect_service", lambda _creds: up)
    monkeypatch.setattr(permissions_demo, "allowed_send", allowed)
    code, lines, creds, _note = permissions_demo.broker_attempt(
        "allowed-send", "solace-demo/permissions/allowed/proof", "client-cloud-permissions-demo"
    )
    shown = permissions_demo._public_result(
        "allowed-send", "client-cloud-permissions-demo", "solace-demo/permissions/allowed/proof", lines, creds
    )
    assert code == 0
    assert calls["n"] == 1
    assert up.is_connected is False
    assert "connection=verified" in lines
    assert shown["connectionVerified"] is True
    assert shown["sessionClosed"] is True
    assert shown["sendReturned"] is True
    assert shown["brokerAck"] is False
    assert shown["result"] == "received"

    down = Session(False)
    monkeypatch.setattr(permissions_demo, "connect_service", lambda _creds: down)
    code, lines, creds, _note = permissions_demo.broker_attempt(
        "allowed-send", "solace-demo/permissions/allowed/proof", "client-cloud-permissions-demo"
    )
    shown = permissions_demo._public_result(
        "allowed-send", "client-cloud-permissions-demo", "solace-demo/permissions/allowed/proof", lines, creds
    )
    assert code == 1
    assert calls["n"] == 1
    assert "connection=verified" not in lines
    assert "session_closed=yes" in lines
    assert shown["connectionVerified"] is False
    assert shown["sessionClosed"] is True
    assert shown["result"] == "failed"
    assert shown["result"] != "denied"
    assert shown["brokerAck"] is False
    assert "authenticated session" in shown["sdk"]


def test_cleanup_reports_closure_without_replacing_the_action(tmp_path, monkeypatch):
    path = tmp_path / "client.json"
    path.write_text(json.dumps({
        "host": "tcps://broker.example:55443",
        "password": "secret-value",
        "username": "client-cloud-permissions-demo",
        "vpn": "ground-station",
    }), encoding="utf-8")
    monkeypatch.setenv("SOLACE_PERMISSIONS_CONFIG", str(path))
    calls = {"action": 0, "disconnect": 0}

    class BrokenFlag:
        def disconnect(self):
            calls["disconnect"] += 1

        @property
        def is_connected(self):
            raise RuntimeError("flag failed secret-value")

    monkeypatch.setattr(permissions_demo, "connect_service", lambda _creds: BrokenFlag())
    monkeypatch.setattr(permissions_demo, "allowed_send", lambda *_args: calls.__setitem__("action", calls["action"] + 1))
    code, lines, creds, _note = permissions_demo.broker_attempt(
        "allowed-send", "solace-demo/permissions/allowed/proof", "client-cloud-permissions-demo"
    )
    shown = permissions_demo._public_result(
        "allowed-send", "client-cloud-permissions-demo", "solace-demo/permissions/allowed/proof", lines, creds
    )
    assert code == 1
    assert calls["action"] == 0
    assert calls["disconnect"] == 1
    assert shown["connectionVerified"] is False
    assert shown["sessionClosed"] is True
    assert shown["result"] == "failed"
    assert shown["result"] != "denied"
    assert "secret-value" not in json.dumps(shown)

    class LeavesOpen:
        is_connected = True

        def disconnect(self):
            calls["disconnect"] += 1
            raise RuntimeError("disconnect failed secret-value SOLCLIENT_SUBCODE_PUBLISH_ACL_DENIED")

    calls["disconnect"] = 0
    monkeypatch.setattr(permissions_demo, "connect_service", lambda _creds: LeavesOpen())
    monkeypatch.setattr(
        permissions_demo,
        "subscribe_once",
        lambda *_args: ["result=denied", "sdk=PubSubPlusCoreClientError: Subscription ACL Denied " + permissions_demo.SUBSCRIBE_DENIAL, "send_returned=no", "broker_ack=no"],
    )
    code, lines, creds, _note = permissions_demo.broker_attempt(
        "subscribe", "solace-demo/permissions/denied/proof", "client-cloud-permissions-demo"
    )
    shown = permissions_demo._public_result(
        "subscribe", "client-cloud-permissions-demo", "solace-demo/permissions/denied/proof", lines, creds
    )
    assert code == 0 or shown["result"] == "denied"
    assert calls["disconnect"] == 1
    assert shown["result"] == "denied"
    assert shown["connectionVerified"] is True
    assert shown["sessionClosed"] is False
    assert shown["brokerAck"] is False
    assert permissions_demo.SUBSCRIBE_DENIAL in shown["sdk"]
    assert permissions_demo.PUBLISH_DENIAL not in shown["sdk"]
    assert "secret-value" not in json.dumps(shown)
    assert "disconnect failed" in shown["closureSdk"]
    assert "[redacted]" in shown["closureSdk"]


def test_lost_response_is_not_called_an_authentication_failure():
    import subprocess
    from pathlib import Path

    page = Path(__file__).resolve().parents[1].joinpath("web", "restricted-operator.html").read_text(encoding="utf-8")
    start = page.index("function attemptStatus")
    end = page.index("function paint")
    script = page[start:end] + r"""
function check(name, status, banned) {
  for (const word of banned) {
    if ((status.mode + " " + status.actor).includes(word)) {
      throw new Error(name + " contains " + word + ": " + status.mode + " | " + status.actor);
    }
  }
}
const lost = attemptStatus(null);
check("lost", lost, ["did not authenticate", "Session closed", "Connection verified"]);
if (lost.mode !== "Result unknown") throw new Error(lost.mode);
if (!lost.actor.includes("unknown")) throw new Error(lost.actor);
const badJson = attemptStatus({ customerText: "Request blocked." });
check("badJson", badJson, ["did not authenticate", "Session closed", "Connection verified"]);
const off = attemptStatus({ result: "off", connectionVerified: false, sessionClosed: null });
check("off", off, ["did not authenticate", "Session closed", "Connection verified"]);
if (!off.actor.includes("not turned on")) throw new Error(off.actor);
const busy = attemptStatus({ result: "busy", connectionVerified: false, sessionClosed: null });
check("busy", busy, ["did not authenticate", "Session closed", "Connection verified"]);
if (!busy.actor.includes("still running")) throw new Error(busy.actor);
const ok = attemptStatus({ result: "received", connectionVerified: true, sessionClosed: true, actor: "perm-demo-user", topic: "solace-demo/permissions/allowed/proof" });
if (ok.mode !== "Session closed") throw new Error(ok.mode);
if (!ok.actor.includes("Connection verified for this attempt")) throw new Error(ok.actor);
if (!ok.actor.startsWith("Session closed. ")) throw new Error(ok.actor);
const unclean = attemptStatus({ result: "denied", connectionVerified: true, sessionClosed: false, actor: "perm-demo-user", topic: "solace-demo/permissions/denied/proof" });
if (unclean.mode === "Session closed") throw new Error(unclean.mode);
if (!unclean.actor.includes("Connection verified for this attempt")) throw new Error(unclean.actor);
if (!unclean.actor.includes("not confirmed")) throw new Error(unclean.actor);
if (unclean.actor.includes("did not authenticate")) throw new Error(unclean.actor);
const down = attemptStatus({ result: "failed", connectionVerified: false, sessionClosed: null, actor: "", topic: "" });
if (!down.actor.startsWith("This attempt did not authenticate.")) throw new Error(down.actor);
if (down.actor.includes("Session closed")) throw new Error(down.actor);
"""
    subprocess.run(["node", "-e", script], check=True)


def test_operator_pages_keep_the_configured_clients_apart(monkeypatch, tmp_path):
    import threading
    import urllib.error
    import urllib.request
    from http.server import ThreadingHTTPServer

    from solace_demo.config import LabConfig
    from solace_demo.live import LiveLab
    from solace_demo.split_client import demo_broker_label, load_split_client
    from solace_demo.web import DemoHandler, public_payload

    calls = {"n": 0}

    def boom(*_args, **_kwargs):
        calls["n"] += 1
        raise AssertionError("restricted client connected")

    monkeypatch.setattr(permissions_demo, "connect_service", boom)
    monkeypatch.delenv("SOLACE_PERMISSIONS_DEMO", raising=False)
    config = LabConfig(
        host="tcp://127.0.0.1:16555",
        vpn="default",
        semp_url="http://127.0.0.1:19081",
        admin_user="admin",
        admin_password="local-admin-secret",
        publisher_username="cloud-publisher-user",
        publisher_password="publisher-secret",
        subscriber_username="local-operator-user",
        subscriber_password="subscriber-secret",
        allow_remote=False,
    )
    lab = LiveLab(config)
    DemoHandler.lab = lab
    DemoHandler.port = 0
    server = ThreadingHTTPServer(("127.0.0.1", 0), DemoHandler)
    port = server.server_address[1]
    DemoHandler.port = port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        def get(path):
            with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as response:
                return response.status, response.read().decode("utf-8")

        status, state_body = get("/api/state")
        state = json.loads(state_body)
        operator_status, operator_page = get("/operator")
        restricted_status, restricted_page = get("/restricted-operator")
        publisher_status, publisher_page = get("/publisher")
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/missing", timeout=5)
            missing_code = 200
        except urllib.error.HTTPError as exc:
            missing_code = exc.code
    finally:
        server.shutdown()
    assert calls["n"] == 0
    assert status == 200
    assert operator_status == restricted_status == publisher_status == 200
    assert missing_code == 404
    assert state["permissionsEnabled"] is False
    assert state["permissionsReady"] is False
    assert state["permissionsBroker"] == ""
    assert state["primaryOperatorClient"] == "local-operator-user"
    assert state["publisherClient"] == "cloud-publisher-user"
    assert state["primaryOperatorBroker"] == "my local Solace broker"
    assert state["operatorBrokerLabel"] == "Solace broker"
    assert "local" not in state["operatorBrokerLabel"]
    assert "127.0.0.1" not in state["operatorBrokerLabel"]
    assert "cloud-publisher-user" not in state["primaryOperatorPath"]
    assert "publisher-secret" not in json.dumps(state)
    assert "subscriber-secret" not in json.dumps(state)
    assert "Primary Operator" in operator_page
    assert "Restricted Operator" in restricted_page
    assert "not turned on" in restricted_page
    assert ">Try to publish to a forbidden topic</button>" in restricted_page
    assert "disabled" in restricted_page
    assert "perm-allow" not in publisher_page
    trust = tmp_path / "trust"
    trust.mkdir()
    cloud_host = "tcps://region." + "messaging" + "." + "solace" + "." + "cloud" + ":55443"
    cloud_name = cloud_host.split("://", 1)[1].rsplit(":", 1)[0]
    monkeypatch.setenv("SOLACE_SPLIT_CLIENT", "1")
    monkeypatch.setenv("SOLACE_PUBLISHER_HOST", cloud_host)
    monkeypatch.setenv("SOLACE_PUBLISHER_VPN", "pub-vpn")
    monkeypatch.setenv("SOLACE_PUBLISHER_USERNAME", "cloud-publisher-user")
    monkeypatch.setenv("SOLACE_PUBLISHER_PASSWORD", "publisher-secret")
    monkeypatch.setenv("SOLACE_PUBLISHER_TRUST_STORE", str(trust))
    monkeypatch.setenv("SOLACE_OPERATOR_HOST", "tcp://127.0.0.1:55554")
    monkeypatch.setenv("SOLACE_OPERATOR_VPN", "op-vpn")
    monkeypatch.setenv("SOLACE_OPERATOR_USERNAME", "local-operator-user")
    monkeypatch.setenv("SOLACE_OPERATOR_PASSWORD", "subscriber-secret")
    split = load_split_client()
    split_state = LiveLab(config, split=split).snapshot()
    cleaned = public_payload(split_state, config, ("publisher-secret", "subscriber-secret", cloud_host, cloud_name))
    assert split_state["primaryOperatorClient"] == "local-operator-user"
    assert split_state["publisherClient"] == "cloud-publisher-user"
    assert split_state["primaryOperatorBroker"] == "my local Solace broker"
    assert split_state["operatorBrokerLabel"] == "Solace broker"
    monkeypatch.setenv("SOLACE_OPERATOR_BROKER_LABEL", "Oracle broker")
    assert LiveLab(config, split=split).snapshot()["operatorBrokerLabel"] == "Oracle broker"
    assert demo_broker_label(split.publisher.host) == "my Solace Cloud broker"
    assert "Bridge to-cloud-unclass carries alerts to the operator broker." in split_state["primaryOperatorPath"]
    assert "does not report" not in split_state["primaryOperatorPath"]
    assert "cloud-publisher-user" not in split_state["primaryOperatorPath"]
    assert cloud_name not in split_state["primaryOperatorPath"]
    assert cleaned["primaryOperatorPath"] == split_state["primaryOperatorPath"]
    assert len(split_state["primaryOperatorPath"]) <= 240
    path = tmp_path / "client.json"
    path.write_text(json.dumps({
        "host": cloud_host,
        "password": "secret-value",
        "username": "client-cloud-permissions-demo",
        "vpn": "ground-station",
    }), encoding="utf-8")
    monkeypatch.setenv("SOLACE_PERMISSIONS_DEMO", "1")
    monkeypatch.setenv("SOLACE_PERMISSIONS_CONFIG", str(path))
    shown = permissions_demo.permissions_status()
    blob = json.dumps(shown)
    assert shown["permissionsClient"] == "client-cloud-permissions-demo"
    assert shown["permissionsBroker"] == "my Solace Cloud broker"
    assert shown["permissionsBrokerLabel"] == "Solace Cloud"
    assert shown["permissionsPath"].endswith(".")
    assert "solace-demo/permissions/allowed/>" in shown["permissionsPolicyNote"]
    assert cloud_name not in blob
    assert "secret-value" not in blob
    assert "ground-station" not in blob
    assert str(path) not in blob
    assert len(shown["permissionsPath"]) <= 240
    assert calls["n"] == 0


def test_permissions_status_does_not_connect_or_invent_a_denial(monkeypatch, tmp_path):
    monkeypatch.delenv("SOLACE_PERMISSIONS_DEMO", raising=False)
    calls = {"n": 0}

    def boom(_creds):
        calls["n"] += 1
        raise RuntimeError("should not connect")

    monkeypatch.setattr(permissions_demo, "connect_service", boom)
    assert permissions_demo.permissions_status()["permissionsEnabled"] is False
    assert permissions_demo.web_attempt("subscribe")["result"] == "off"
    monkeypatch.setenv("SOLACE_PERMISSIONS_DEMO", "1")
    monkeypatch.setenv("SOLACE_PERMISSIONS_CONFIG", str(tmp_path / "missing.json"))
    status = permissions_demo.permissions_status()
    assert status["permissionsEnabled"] is True
    assert status["permissionsReady"] is False
    missed = permissions_demo.web_attempt("subscribe")
    assert missed["result"] == "failed"
    assert missed["result"] != "denied"
    assert calls["n"] == 0
    path = tmp_path / "client.json"
    path.write_text(json.dumps({
        "host": "tcp://127.0.0.1:9",
        "password": "secret-value",
        "username": "client-cloud-permissions-demo",
        "vpn": "default",
    }), encoding="utf-8")
    monkeypatch.setenv("SOLACE_PERMISSIONS_CONFIG", str(path))
    monkeypatch.setenv("SOLACE_PERMISSIONS_ALLOW_LOOPBACK", "1")

    def explode(creds):
        raise RuntimeError("connect failed " + creds["host"] + " " + creds["password"])

    monkeypatch.setattr(permissions_demo, "connect_service", explode)
    failed = permissions_demo.web_attempt("publish-guaranteed")
    assert failed["result"] == "failed"
    assert failed["result"] != "denied"
    blob = json.dumps(failed)
    assert "secret-value" not in blob
    assert "127.0.0.1" not in blob
    assert calls["n"] == 0


def test_real_acl_denies_on_a_disposable_broker(monkeypatch, tmp_path):
    if not os.environ.get("SOLACE_ADMIN_PASSWORD"):
        pytest.skip("SOLACE_ADMIN_PASSWORD is not set; permissions broker test not run")
    from solace_demo.config import ConfigError, load_config
    from solace_demo.provision import (
        ensure_acl_profile,
        ensure_client_profile,
        ensure_client_username,
        ensure_topic_exception,
        wait_until_ready,
    )
    from solace_demo.semp import Semp, SempError

    try:
        config = load_config()
        wait_until_ready(config, attempts=5, pause_seconds=1)
    except (ConfigError, SempError) as exc:
        pytest.skip(f"local broker not ready: {exc}")
    semp = Semp(config)
    ensure_client_profile(semp, config, "perm-demo-client", send=True, receive=True)
    ensure_acl_profile(semp, config, "perm-demo-acl")
    ensure_topic_exception(semp, config, "perm-demo-acl", "publish", "solace-demo/permissions/allowed/>")
    ensure_topic_exception(semp, config, "perm-demo-acl", "subscribe", "solace-demo/permissions/allowed/>")
    ensure_client_username(
        semp, config, "perm-demo-user", "perm-demo-pass", "perm-demo-acl", "perm-demo-client",
        allow_remote_update=True,
    )
    path = tmp_path / "client.json"
    path.write_text(json.dumps({
        "host": config.host,
        "password": "perm-demo-pass",
        "username": "perm-demo-user",
        "vpn": config.vpn,
    }), encoding="utf-8")
    monkeypatch.setenv("SOLACE_PERMISSIONS_CONFIG", str(path))
    monkeypatch.setenv("SOLACE_PERMISSIONS_ALLOW_LOOPBACK", "1")
    monkeypatch.setenv("SOLACE_PERMISSIONS_EVIDENCE_DIR", str(tmp_path / "evidence"))
    allowed = run([
        "allowed-send",
        "--client", "perm-demo-user",
        "--topic", "solace-demo/permissions/allowed/proof",
    ])
    denied_sub = run([
        "subscribe",
        "--client", "perm-demo-user",
        "--topic", "solace-demo/permissions/denied/proof",
    ])
    denied_pub = run([
        "publish-guaranteed",
        "--client", "perm-demo-user",
        "--topic", "solace-demo/permissions/denied/proof",
    ])
    logs = sorted((tmp_path / "evidence").glob("*.log"))
    combined = "\n".join(path.read_text(encoding="utf-8") for path in logs)
    assert "perm-demo-pass" not in combined
    assert allowed == 0
    allowed_log = [item.read_text(encoding="utf-8") for item in logs if "-allowed-send-" in item.name][0]
    assert "result=received" in allowed_log
    assert "connection=verified" in allowed_log
    assert "broker_ack=no" in allowed_log
    assert "broker_ack=yes" not in allowed_log
    sent = [line.split("=", 1)[1] for line in allowed_log.splitlines() if line.startswith("sent_id=")]
    received = [line.split("=", 1)[1] for line in allowed_log.splitlines() if line.startswith("received_id=")]
    assert sent and sent == received
    assert "received_topic=solace-demo/permissions/allowed/proof" in allowed_log
    other_code, other_lines, _used, _note = permissions_demo.broker_attempt(
        "allowed-send", "solace-demo/permissions/allowed/another", "perm-demo-user"
    )
    assert other_code == 0
    assert "result=received" in other_lines
    assert "received_topic=solace-demo/permissions/allowed/another" in other_lines
    assert denied_sub == 0
    assert SUBSCRIBE_DENIAL in combined
    assert denied_pub == 0
    assert PUBLISH_DENIAL in combined
    assert combined.count("connection=verified") >= 3
    assert len(logs) == 3


def test_three_http_actions_on_a_disposable_broker(monkeypatch, tmp_path):
    if not os.environ.get("SOLACE_ADMIN_PASSWORD"):
        pytest.skip("SOLACE_ADMIN_PASSWORD is not set; permissions HTTP test not run")
    import threading
    from http.server import ThreadingHTTPServer
    import urllib.request

    from solace_demo.config import ConfigError, load_config
    from solace_demo.live import LiveLab
    from solace_demo.provision import (
        ensure_acl_profile,
        ensure_client_profile,
        ensure_client_username,
        ensure_topic_exception,
        ensure_web_queue,
        provision,
        wait_until_ready,
    )
    from solace_demo.semp import Semp, SempError
    from solace_demo.web import DemoHandler

    try:
        config = load_config()
        wait_until_ready(config, attempts=5, pause_seconds=1)
    except (ConfigError, SempError) as exc:
        pytest.skip(f"local broker not ready: {exc}")
    provision(config)
    semp = Semp(config)
    ensure_client_profile(semp, config, "perm-demo-client", send=True, receive=True)
    ensure_acl_profile(semp, config, "perm-demo-acl")
    ensure_topic_exception(semp, config, "perm-demo-acl", "publish", "solace-demo/permissions/allowed/>")
    ensure_topic_exception(semp, config, "perm-demo-acl", "subscribe", "solace-demo/permissions/allowed/>")
    ensure_client_username(
        semp, config, "perm-demo-user", "perm-demo-pass", "perm-demo-acl", "perm-demo-client",
        allow_remote_update=True,
    )
    ensure_web_queue(semp, config)
    path = tmp_path / "client.json"
    path.write_text(json.dumps({
        "host": config.host,
        "password": "perm-demo-pass",
        "username": "perm-demo-user",
        "vpn": config.vpn,
    }), encoding="utf-8")
    monkeypatch.setenv("SOLACE_PERMISSIONS_DEMO", "1")
    monkeypatch.setenv("SOLACE_PERMISSIONS_CONFIG", str(path))
    monkeypatch.setenv("SOLACE_PERMISSIONS_ALLOW_LOOPBACK", "1")
    monkeypatch.setenv("SOLACE_PERMISSIONS_EVIDENCE_DIR", str(tmp_path / "evidence"))
    lab = LiveLab(config)
    lab.open()
    DemoHandler.lab = lab
    DemoHandler.port = 8899
    server = ThreadingHTTPServer(("127.0.0.1", 8899), DemoHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def post(action):
        req = urllib.request.Request(
            "http://127.0.0.1:8899/api/permissions",
            data=json.dumps({"action": action, "topic": "admin/test/probe", "password": "injected"}).encode(),
            headers={"Content-Type": "application/json", "Origin": "http://127.0.0.1:8899", "Host": "127.0.0.1:8899"},
        )
        with urllib.request.urlopen(req, timeout=20) as response:
            return json.load(response)

    try:
        state = json.load(urllib.request.urlopen("http://127.0.0.1:8899/api/state", timeout=5))
        restricted = urllib.request.urlopen("http://127.0.0.1:8899/restricted-operator", timeout=5).read().decode("utf-8")
        operator_page = urllib.request.urlopen("http://127.0.0.1:8899/operator", timeout=5).read().decode("utf-8")
        publisher_page = urllib.request.urlopen("http://127.0.0.1:8899/publisher", timeout=5).read().decode("utf-8")
        assert state["permissionsEnabled"] is True
        assert state["permissionsClient"] == "perm-demo-user"
        from solace_demo.split_client import demo_broker_label

        assert state["permissionsBroker"] == demo_broker_label(config.host)
        assert state["primaryOperatorClient"] == config.subscriber_username
        assert state["publisherClient"] == config.publisher_username
        assert state["primaryOperatorClient"] != "perm-demo-user" or config.subscriber_username == "perm-demo-user"
        assert "Try to publish to a forbidden topic" in restricted
        assert "Send one guaranteed message" not in restricted
        assert "/api/send" not in restricted
        assert "Primary Operator" in operator_page
        assert "perm-allow" not in publisher_page
        assert "perm-demo-pass" not in json.dumps(state)
        assert config.host not in json.dumps(state)
        assert "connectionVerified" not in state
        allowed = post("allowed-send")
        denied_sub = post("subscribe")
        denied_pub = post("publish-guaranteed")
    finally:
        server.shutdown()
        lab.close()
    assert allowed["result"] == "received"
    assert allowed["connectionVerified"] is True
    assert allowed["sessionClosed"] is True
    assert allowed["sendReturned"] is True
    assert allowed["brokerAck"] is False
    assert allowed["sentId"] and allowed["sentId"] == allowed["receivedId"]
    assert allowed["receivedTopic"] == "solace-demo/permissions/allowed/proof"
    assert allowed["topic"] == "solace-demo/permissions/allowed/proof"
    assert denied_sub["result"] == "denied"
    assert denied_sub["connectionVerified"] is True
    assert denied_sub["sessionClosed"] is True
    assert denied_sub["brokerAck"] is False
    assert "SOLCLIENT_SUBCODE_SUBSCRIPTION_ACL_DENIED" in denied_sub["sdk"]
    assert denied_pub["result"] == "denied"
    assert denied_pub["connectionVerified"] is True
    assert denied_pub["sessionClosed"] is True
    assert denied_pub["brokerAck"] is False
    assert denied_pub["sendReturned"] is False
    assert "SOLCLIENT_SUBCODE_PUBLISH_ACL_DENIED" in denied_pub["sdk"]
    assert "perm-demo-pass" not in json.dumps([allowed, denied_sub, denied_pub])
    assert "injected" not in denied_sub["topic"]
