"""Page role: publisher on one host, operators on another."""

from __future__ import annotations

import json
import threading
import time
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from solace.messaging.errors.pubsubplus_client_error import MessageRejectedByBrokerError

from solace_demo.config import LabConfig
from solace_demo.live import LiveLab
from solace_demo.split_client import load_split_client
from solace_demo.web import DemoHandler


def _config() -> LabConfig:
    return LabConfig(
        host="tcp://127.0.0.1:9",
        vpn="default",
        semp_url="http://127.0.0.1:9",
        admin_user="admin",
        admin_password="local-only",
        publisher_username="pub-user",
        publisher_password="pub-secret",
        subscriber_username="op-user",
        subscriber_password="op-secret",
        allow_remote=False,
    )


def _serve(lab):
    DemoHandler.lab = lab
    DemoHandler.bind_host = "127.0.0.1"
    server = ThreadingHTTPServer(("127.0.0.1", 0), DemoHandler)
    DemoHandler.port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _get(port, path):
    try:
        with urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as response:
            return response.status, response.read().decode("utf-8"), response.geturl()
    except HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace"), ""


def _publisher_env(monkeypatch):
    monkeypatch.setenv("SOLACE_SPLIT_CLIENT", "1")
    monkeypatch.setenv("SOLACE_PUBLISHER_HOST", "tcp://127.0.0.1:16655")
    monkeypatch.setenv("SOLACE_PUBLISHER_VPN", "pub-vpn")
    monkeypatch.setenv("SOLACE_PUBLISHER_USERNAME", "cloud-publisher")
    monkeypatch.setenv("SOLACE_PUBLISHER_PASSWORD", "pub-secret")
    monkeypatch.delenv("SOLACE_OPERATOR_HOST", raising=False)
    monkeypatch.delenv("SOLACE_OPERATOR_VPN", raising=False)
    monkeypatch.delenv("SOLACE_OPERATOR_USERNAME", raising=False)
    monkeypatch.delenv("SOLACE_OPERATOR_PASSWORD", raising=False)
    monkeypatch.delenv("SOLACE_OPERATOR_AUTH", raising=False)


def _operator_env(monkeypatch):
    monkeypatch.setenv("SOLACE_SPLIT_CLIENT", "1")
    monkeypatch.setenv("SOLACE_OPERATOR_HOST", "tcp://127.0.0.1:55554")
    monkeypatch.setenv("SOLACE_OPERATOR_VPN", "default")
    monkeypatch.setenv("SOLACE_OPERATOR_USERNAME", "default")
    monkeypatch.setenv("SOLACE_OPERATOR_AUTH", "none")
    monkeypatch.delenv("SOLACE_PUBLISHER_HOST", raising=False)
    monkeypatch.delenv("SOLACE_PUBLISHER_VPN", raising=False)
    monkeypatch.delenv("SOLACE_PUBLISHER_USERNAME", raising=False)
    monkeypatch.delenv("SOLACE_PUBLISHER_PASSWORD", raising=False)


def test_publisher_role_serves_only_the_publisher(monkeypatch):
    _publisher_env(monkeypatch)
    monkeypatch.setenv("SOLACE_WEB_ROLE", "publisher")
    monkeypatch.setenv("SOLACE_PERMISSIONS_DEMO", "1")
    monkeypatch.setenv("SOLACE_PERMISSIONS_CONFIG", "/tmp/missing-permissions-role.json")
    split = load_split_client("publisher")
    assert split.operator is None
    assert split.publisher.username == "cloud-publisher"
    lab = LiveLab(_config(), split=split, role="publisher")

    class Up:
        is_connected = True

    lab._publisher = Up()
    assert lab._sessions_report_connected() is True
    state = lab.snapshot()
    assert state["webRole"] == "publisher"
    assert state["permissionsEnabled"] is False
    assert state["publisherClient"] == "cloud-publisher"
    assert state["operatorStatus"] == ""
    assert state["publisherName"] == "local lab broker"
    server = _serve(lab)
    port = server.server_address[1]
    try:
        home = _get(port, "/")
        assert home[0] == 200
        assert home[2].endswith("/publisher")
        page = _get(port, "/publisher")
        assert page[0] == 200
        assert "Publisher" in page[1]
        assert 'href="/operator"' not in page[1]
        assert 'href="/restricted-operator"' not in page[1]
        assert _get(port, "/operator")[0] == 404
        assert _get(port, "/restricted-operator")[0] == 404
        blocked = Request(
            f"http://127.0.0.1:{port}/api/listen",
            data=b"{}",
            headers={"Content-Type": "application/json", "Host": f"127.0.0.1:{port}"},
            method="POST",
        )
        try:
            urlopen(blocked, timeout=5)
            status = 200
        except HTTPError as exc:
            status = exc.code
        assert status == 404
    finally:
        server.shutdown()


def test_operators_role_serves_only_the_operator_pages(monkeypatch):
    _operator_env(monkeypatch)
    monkeypatch.setenv("SOLACE_WEB_ROLE", "operators")
    split = load_split_client("operators")
    assert split.publisher is None
    assert split.operator.username == "default"
    lab = LiveLab(_config(), split=split, role="operators")

    class Up:
        is_connected = True

    lab._subscriber = Up()
    assert lab._sessions_report_connected() is True
    lab.role = "all"
    assert lab._sessions_report_connected() is False
    lab.role = "operators"
    state = lab.snapshot()
    assert state["webRole"] == "operators"
    assert state["primaryOperatorClient"] == "default"
    assert state["publisherStatus"] == ""
    server = _serve(lab)
    port = server.server_address[1]
    try:
        home = _get(port, "/")
        assert home[0] == 200
        assert home[2].endswith("/operator")
        operator = _get(port, "/operator")
        restricted = _get(port, "/restricted-operator")
        assert operator[0] == 200
        assert restricted[0] == 200
        assert 'href="/publisher"' not in operator[1]
        assert "Primary Operator" in operator[1]
        assert "Restricted Operator" in operator[1]
        assert "Primary Operator" in restricted[1]
        assert "Restricted Operator" in restricted[1]
        assert _get(port, "/publisher")[0] == 404
        body = json.dumps({"kind": "launch-ground1"}).encode()
        blocked = Request(
            f"http://127.0.0.1:{port}/api/send",
            data=body,
            headers={"Content-Type": "application/json", "Host": f"127.0.0.1:{port}"},
            method="POST",
        )
        try:
            urlopen(blocked, timeout=5)
            status = 200
        except HTTPError as exc:
            status = exc.code
        assert status == 404
    finally:
        server.shutdown()


class _Up:
    is_connected = True


def _mark_connected(lab):
    lab.broker_connected = True
    lab._probed_at = time.time()


def _post_json(port, path, payload):
    body = json.dumps(payload).encode()
    request = Request(
        f"http://127.0.0.1:{port}{path}",
        data=body,
        headers={"Content-Type": "application/json", "Host": f"127.0.0.1:{port}"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=5) as response:
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw) if raw else {}
    except HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            parsed = {}
        return exc.code, parsed


def _post_send(port, kind):
    body = json.dumps({"kind": kind}).encode()
    request = Request(
        f"http://127.0.0.1:{port}/api/send",
        data=body,
        headers={"Content-Type": "application/json", "Host": f"127.0.0.1:{port}"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_publisher_role_guaranteed_follows_the_prefix_not_the_operator_queue(monkeypatch):
    _publisher_env(monkeypatch)
    monkeypatch.setenv("SOLACE_WEB_ROLE", "publisher")
    monkeypatch.delenv("SOLACE_GUARANTEED_TOPIC_PREFIX", raising=False)
    bare = load_split_client("publisher")
    lab = LiveLab(_config(), split=bare, role="publisher")
    lab._publisher = _Up()
    _mark_connected(lab)
    assert lab.guaranteed_available is False
    state = lab.snapshot()
    assert state["guaranteedAvailable"] is False
    assert "Queue" not in state["guaranteedNote"]
    assert "consumer" not in state["guaranteedNote"].lower()
    calls = []

    def publish(topic, alert_id, body, delivery):
        calls.append((topic, delivery))

    lab._publish = publish
    blocked = lab.send("guaranteed-launch")
    assert blocked["outcome"] == "not-sent"
    assert blocked["brokerAck"] is False
    assert calls == []

    monkeypatch.setenv("SOLACE_GUARANTEED_TOPIC_PREFIX", "ssa-guaranteed/unclass")
    split = load_split_client("publisher")
    ready = LiveLab(_config(), split=split, role="publisher")
    ready._publisher = _Up()
    _mark_connected(ready)
    assert ready.guaranteed_available is False
    note = ready.snapshot()["guaranteedNote"]
    topic = "ssa-guaranteed/unclass/ground1/launch/25544/alert"
    assert ready.snapshot()["guaranteedAvailable"] is True
    assert note == f"Topic {topic}. A broker ACK means the broker accepted it."
    assert "Queue" not in note
    assert "consumer" not in note.lower()
    assert len(note) <= 240

    def ack(topic, alert_id, body, delivery):
        calls.append((topic, delivery))

    ready._publish = ack
    server = _serve(ready)
    port = server.server_address[1]
    try:
        status, payload = _post_send(port, "guaranteed-launch")
        assert status == 200
        assert payload["outcome"] == "acked"
        assert payload["brokerAck"] is True
        assert payload["topic"] == topic
        assert calls == [(topic, "guaranteed")]
        calls.clear()

        def nack(topic, alert_id, body, delivery):
            calls.append((topic, delivery))
            raise MessageRejectedByBrokerError("SOLCLIENT_SUBCODE_PUBLISH_ACL_DENIED")

        ready._publish = nack
        status, refused = _post_send(port, "guaranteed-launch")
        assert status == 200
        assert refused["outcome"] == "refused"
        assert refused["brokerAck"] is False
        assert "refused" in refused["customerText"]
        assert calls == [(topic, "guaranteed")]
    finally:
        server.shutdown()

    down = LiveLab(_config(), split=split, role="publisher")
    down._publisher = _Up()
    down.broker_connected = False
    down._probed_at = time.time()
    assert down.snapshot()["guaranteedAvailable"] is False


def test_role_all_guaranteed_still_needs_the_operator_queue_bind(monkeypatch):
    _publisher_env(monkeypatch)
    monkeypatch.setenv("SOLACE_OPERATOR_HOST", "tcp://127.0.0.1:16755")
    monkeypatch.setenv("SOLACE_OPERATOR_VPN", "op-vpn")
    monkeypatch.setenv("SOLACE_OPERATOR_USERNAME", "op-user")
    monkeypatch.setenv("SOLACE_OPERATOR_PASSWORD", "op-secret")
    monkeypatch.setenv("SOLACE_OPERATOR_QUEUE", "queue-local-operator-guaranteed")
    monkeypatch.setenv("SOLACE_GUARANTEED_TOPIC_PREFIX", "ssa-guaranteed/unclass")
    monkeypatch.delenv("SOLACE_WEB_ROLE", raising=False)
    split = load_split_client("all")
    lab = LiveLab(_config(), split=split, role="all")
    lab._publisher = _Up()
    lab._subscriber = _Up()
    _mark_connected(lab)
    assert lab.snapshot()["guaranteedAvailable"] is False
    assert "queue-local-operator-guaranteed" in lab.snapshot()["guaranteedNote"]
    calls = []
    lab._publish = lambda topic, alert_id, body, delivery: calls.append(delivery)
    blocked = lab.send("guaranteed-launch")
    assert blocked["outcome"] == "not-sent"
    assert calls == []
    lab.guaranteed_available = True
    assert lab.snapshot()["guaranteedAvailable"] is True
    sent = lab.send("guaranteed-launch")
    assert sent["outcome"] == "acked"
    assert sent["brokerAck"] is True
    assert calls == ["guaranteed"]

    operators = LiveLab(_config(), split=split, role="operators")
    operators._subscriber = _Up()
    _mark_connected(operators)
    assert operators.snapshot()["guaranteedAvailable"] is False
    operators.guaranteed_available = True
    assert operators.snapshot()["guaranteedAvailable"] is True


def _record(lab, alert_id, feed, queue=False, redelivered=False, draining=False):
    lab._generation = 1
    return lab._record(
        1,
        feed,
        {"alertId": alert_id, "topic": "ssa/unclass/ground1/launch/25544/alert"},
        queue=queue,
        redelivered=redelivered,
        draining=draining,
    )


def test_operators_label_live_arrivals_and_keep_the_queue_backlog_label():
    operators = LiveLab(_config(), role="operators")
    recorded, ack = _record(operators, "direct-live", "one-object-ground1-25544")
    assert recorded is True
    assert ack is True
    assert operators._events[-1]["origin"] == "this-session"
    assert operators._events[-1]["delivery"] == "direct"
    _record(operators, "spooled", "broker-queue", queue=True, draining=True)
    assert operators._events[-1]["origin"] == "already-queued"
    assert operators._events[-1]["delivery"] == "queued"
    _record(operators, "redelivered", "broker-queue", queue=True, redelivered=True)
    assert operators._events[-1]["origin"] == "already-queued"
    _record(operators, "after-bind", "broker-queue", queue=True)
    assert operators._events[-1]["origin"] == "this-session"

    class Split:
        guaranteed_prefix = ""

    combined = LiveLab(_config(), split=Split(), role="all")
    combined._published["mine"] = {"topic": "t", "delivery": "guaranteed", "kind": "guaranteed-launch"}
    _record(combined, "mine", "broker-queue", queue=True, draining=True)
    assert combined._events[-1]["origin"] == "this-session"
    _, left = _record(combined, "older", "broker-queue", queue=True)
    assert combined._events[-1]["origin"] == "already-queued"
    assert left is False
    local = LiveLab(_config(), role="all")
    _, acked = _record(local, "older-local", "broker-queue", queue=True, draining=True)
    assert local._events[-1]["origin"] == "already-queued"
    assert acked is True


def test_clear_removes_one_card_from_the_page_history(monkeypatch):
    from pathlib import Path

    monkeypatch.setenv("SOLACE_WEB_ROLE", "operators")
    root = Path(__file__).resolve().parents[1] / "web"
    page = (root / "operator.html").read_text(encoding="utf-8")
    restricted = (root / "restricted-operator.html").read_text(encoding="utf-8")
    assert page.count(">Clear<") == 3
    assert 'data-clear="launch-any-site"' in page
    assert 'data-clear="one-object-ground1-25544"' in page
    assert "appears after Disconnect" not in page
    assert "Queue holding ${state.queueDepth}" in page
    assert 'class="clear"' not in restricted
    assert 'class="feed"' not in restricted
    lab = LiveLab(_config(), role="operators")
    _record(lab, "launch-1", "launch-any-site")
    _record(lab, "direct-1", "one-object-ground1-25544")
    _record(lab, "queued-1", "broker-queue", queue=True, draining=True)
    server = _serve(lab)
    port = server.server_address[1]
    try:
        status, body = _post_json(port, "/api/clear", {"feed": "one-object-ground1-25544"})
        assert status == 200
        assert body["ok"] is True
        assert [event["alertId"] for event in lab.snapshot()["events"]] == ["launch-1"]
        status, body = _post_json(port, "/api/clear", {"feed": "launch-any-site"})
        assert status == 200
        assert lab.snapshot()["events"] == []
        status, _body = _post_json(port, "/api/clear", {"feed": "broker-queue"})
        assert status == 400
    finally:
        server.shutdown()


def test_ground2_queued_receipt_is_acked_and_kept_off_the_ground1_card():
    from solace_demo.live import display_feed

    lab = LiveLab(_config(), role="operators")
    lab._generation = 1
    recorded, ack = lab._record(
        1,
        "broker-queue",
        {
            "alertId": "g2",
            "topic": "ssa-guaranteed/unclass/ground2/launch/25544/alert",
            "site": "ground2",
        },
        queue=True,
    )
    assert recorded is True
    assert ack is True
    assert lab._events[-1]["delivery"] == "queued"
    assert display_feed(lab._events[-1]) == ""
    _record(lab, "g1", "broker-queue", queue=True, draining=True)
    assert display_feed(lab._events[-1]) == "one-object-ground1-25544"
    lab.clear_display("one-object-ground1-25544")
    assert [event["alertId"] for event in lab._events] == ["g2"]


def test_role_all_still_serves_every_page(monkeypatch):
    monkeypatch.delenv("SOLACE_WEB_ROLE", raising=False)
    lab = LiveLab(_config(), role="all")
    server = _serve(lab)
    port = server.server_address[1]
    try:
        publisher = _get(port, "/publisher")
        operator = _get(port, "/operator")
        assert publisher[0] == 200
        assert operator[0] == 200
        assert 'href="/publisher"' in publisher[1]
        assert 'href="/operator"' in publisher[1]
        assert 'href="/restricted-operator"' in publisher[1]
        assert lab.snapshot()["webRole"] == "all"
        missing = _get(port, "/api/missing")
        assert missing[0] == 404
        assert json.loads(missing[1])["error"] == "not found"
    finally:
        server.shutdown()


def test_weather_card_can_be_cleared():
    lab = LiveLab(_config(), role="operators")
    lab._generation = 1
    _record(lab, "w1", "weather-ground1")
    _record(lab, "l1", "launch-any-site")
    lab.clear_display("weather-ground1")
    assert [event["alertId"] for event in lab._events] == ["l1"]
