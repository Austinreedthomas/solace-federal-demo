"""Browser-lab fidelity. Broker cases skip unless the isolated lab answers.

A skip is not a pass. These tests do not bind q-ssa-operator.
"""

from __future__ import annotations

import os
import threading
import time

import pytest

from solace_demo.catalog import QUEUE_NAME, TOPIC_BOTH, WEB_QUEUE_NAME
from solace_demo.config import ConfigError, LabConfig, load_config
from solace_demo.live import (
    DIRECT_CUSTOMER_TEXT,
    GUARANTEED_CUSTOMER_TEXT,
    LiveLab,
    not_sent,
    publish_outcome,
    receipt_matches,
)
from solace_demo.provision import provision, wait_until_ready
from solace_demo.semp import Semp, SempError
from solace_demo.web import public_payload


def test_direct_send_is_not_described_as_a_broker_ack():
    direct = publish_outcome("direct")
    guaranteed = publish_outcome("guaranteed")
    assert direct["outcome"] == "sent"
    assert direct["sendReturned"] is True
    assert direct["brokerAck"] is False
    assert direct["customerText"] == DIRECT_CUSTOMER_TEXT
    assert "The broker acknowledged this alert." not in direct["customerText"]
    assert "brokerAccepted" not in direct
    assert guaranteed["outcome"] == "acked"
    assert guaranteed["brokerAck"] is True
    assert "when the same id arrives" in guaranteed["customerText"]
    assert "does not mean" not in guaranteed["customerText"]
    assert guaranteed["customerText"] == GUARANTEED_CUSTOMER_TEXT


def test_receipt_line_cannot_endorse_a_different_send():
    event = {"alertId": "ex-new", "origin": "this-session"}
    assert receipt_matches("ex-new", "2", "2", event) is True
    assert receipt_matches("ex-new", "2", "1", event) is False
    assert receipt_matches("ex-old", "2", "2", event) is False
    assert receipt_matches("ex-new", "2", "2", {"alertId": "ex-new", "origin": "already-queued"}) is False
    missed = not_sent("The lab broker is not connected. Nothing was sent.")
    assert missed["outcome"] == "not-sent"
    assert missed["brokerAck"] is False
    assert missed["brokerAccepted"] is False


def test_every_http_string_is_redacted():
    config = LabConfig(
        host="tcp://127.0.0.1:16555",
        vpn="default",
        semp_url="http://127.0.0.1:19081",
        admin_user="admin",
        admin_password="local-only",
        publisher_username="ssa-publisher",
        publisher_password="publisher-secret",
        subscriber_username="ssa-subscriber",
        subscriber_password="subscriber-secret",
        allow_remote=False,
    )
    cleaned = public_payload(
        {
            "detail": "failed local-only publisher-secret",
            "lastError": "subscriber-secret in the session",
            "events": [{"topic": "ssa/unclass/ground1/launch/25544/alert", "alertText": "Launch detected"}],
            "nested": {"note": "publisher-secret"},
        },
        config,
    )
    blob = str(cleaned)
    assert "local-only" not in blob
    assert "publisher-secret" not in blob
    assert "subscriber-secret" not in blob
    assert "Launch detected" in blob
    assert "[redacted]" in blob


def test_failed_receiver_startup_does_not_leave_listeners():
    lab = LiveLab(
        LabConfig(
            host="tcp://127.0.0.1:9",
            vpn="default",
            semp_url="http://127.0.0.1:9",
            admin_user="admin",
            admin_password="local-only",
            publisher_username="ssa-publisher",
            publisher_password="local-only",
            subscriber_username="ssa-subscriber",
            subscriber_password="local-only",
            allow_remote=False,
        )
    )
    created = []

    class Fake:
        def __init__(self):
            self.terminated = False
            created.append(self)

        def terminate(self):
            self.terminated = True

        def receive_message(self, timeout=0):
            raise RuntimeError("stopped")

    def start(subscription, queue):
        if len(created) == 2:
            raise RuntimeError("bind failed")
        return Fake()

    lab.broker_connected = True
    lab._subscriber = object()
    lab._start_receiver = start
    with pytest.raises(RuntimeError, match="bind failed"):
        with lab._session_lock:
            lab._listen_locked()
    assert lab.listening is False
    assert lab._receivers == []
    assert created
    assert all(item.terminated for item in created)
    assert not any(thread.is_alive() for thread in lab._threads)


def _broker_config():
    if not os.environ.get("SOLACE_ADMIN_PASSWORD"):
        pytest.skip("SOLACE_ADMIN_PASSWORD is not set; broker fidelity not run")
    try:
        config = load_config()
    except ConfigError as exc:
        pytest.skip(str(exc))
    try:
        wait_until_ready(config, attempts=5, pause_seconds=1)
    except SempError as exc:
        pytest.skip(f"local broker not ready: {exc}")
    return config


def _message_count(config, queue_name: str) -> int:
    payload = Semp(config, timeout=2.0).request(
        "GET",
        f"/SEMP/v2/monitor/msgVpns/{config.vpn}/queues/{queue_name}/msgs?count=100",
    )
    count = payload.get("meta", {}).get("count")
    assert isinstance(count, int)
    return count


def _flows(config, queue_name: str) -> int:
    payload = Semp(config, timeout=2.0).request(
        "GET",
        f"/SEMP/v2/monitor/msgVpns/{config.vpn}/queues/{queue_name}/txFlows",
    )
    data = payload.get("data") or []
    return len(data)


def test_web_queue_shows_history_and_does_not_ack_the_quickstart_queue():
    config = _broker_config()
    from solace_demo.messaging import connect, disconnect, publish_persistent
    from solace_demo.provision import ensure_web_queue

    provision(config)
    ensure_web_queue(Semp(config), config)
    before = _message_count(config, QUEUE_NAME)
    service = connect(config, config.publisher_username, config.publisher_password)
    historical = "history-" + str(time.time_ns())
    try:
        publish_persistent(
            service,
            TOPIC_BOTH,
            historical,
            {
                "alertId": historical,
                "alertText": "Launch detected",
                "topic": TOPIC_BOTH,
                "site": "ground1",
                "kind": "launch",
                "objectId": "25544",
                "synthetic": True,
                "classificationLabel": "unclass",
            },
        )
    finally:
        disconnect([service])
    lab = LiveLab(config)
    lab.open()
    try:
        found = None
        for _ in range(20):
            for event in lab.snapshot()["events"]:
                if event["alertId"] == historical and event["feed"] == "broker-queue":
                    found = event
                    break
            if found:
                break
            time.sleep(0.2)
        assert found is not None
        assert found["origin"] == "already-queued"
        assert _message_count(config, QUEUE_NAME) >= before + 1
        lab.disconnect_operator()
        assert lab.snapshot()["operatorListening"] is False
        assert _flows(config, WEB_QUEUE_NAME) == 0
        sent = lab.send("guaranteed-launch")
        assert sent["outcome"] == "acked"
        assert sent["brokerAck"] is True
        time.sleep(0.8)
        assert all(event["alertId"] != sent["alertId"] for event in lab.snapshot()["events"])
        assert lab.queue_depth() >= 1
        again = lab.connect_operator()
        assert again["operatorListening"] is True
        assert _flows(config, WEB_QUEUE_NAME) == 1
        arrived = None
        for _ in range(20):
            for event in lab.snapshot()["events"]:
                if event["alertId"] == sent["alertId"] and event["feed"] == "broker-queue":
                    arrived = event
                    break
            if arrived:
                break
            time.sleep(0.2)
        assert arrived is not None
        assert arrived["origin"] == "this-session"
        assert arrived["delivery"] == "queued"
        assert arrived["topic"] == TOPIC_BOTH
        assert arrived["site"] == "ground1"
        direct = lab.send("launch-ground1")
        assert direct["outcome"] == "sent"
        assert direct["brokerAck"] is False
        assert "The broker acknowledged this alert." not in direct["customerText"]
    finally:
        lab.close()


def test_broker_stop_after_startup_does_not_stay_green_and_connect_recovers(monkeypatch):
    stop_host = os.environ.get("SOLACE_TEST_STOP_HOST", "").strip()
    stop_semp = os.environ.get("SOLACE_TEST_STOP_SEMP", "").strip()
    container = os.environ.get("SOLACE_TEST_STOP_CONTAINER", "solace-visual-repro").strip() or "solace-visual-repro"
    if stop_host or stop_semp:
        if "16555" not in stop_host or not stop_semp:
            pytest.skip("broker-loss test only stops the disposable broker published on 16555")
        monkeypatch.setenv("SOLACE_HOST", stop_host)
        monkeypatch.setenv("SOLACE_SEMP_URL", stop_semp)
    config = _broker_config()
    if "16555" not in config.host:
        pytest.skip("broker-loss test only stops the disposable broker published on 16555")
    import subprocess

    from solace_demo.provision import ensure_web_queue

    provision(config)
    ensure_web_queue(Semp(config), config)
    lab = LiveLab(config)
    lab.open()
    stopped = False
    try:
        first = lab.send("launch-ground1")
        assert first["outcome"] == "sent"
        seen = False
        for _ in range(20):
            if any(event["alertId"] == first["alertId"] and event["origin"] == "this-session" for event in lab.snapshot()["events"]):
                seen = True
                break
            time.sleep(0.2)
        assert seen
        subprocess.check_call(["sudo", "docker", "stop", container], stdout=subprocess.DEVNULL)
        stopped = True
        denied = lab.send("launch-ground2")
        assert denied["outcome"] == "not-sent"
        assert denied["brokerAck"] is False
        assert denied["brokerAccepted"] is False
        assert "Nothing was sent" in denied["customerText"]
        state = lab.snapshot()
        assert state["brokerConnected"] is False
        assert state["operatorListening"] is False
        assert state["queueDepth"] is None
        assert all(event["alertId"] != "ex-not-a-real-id" for event in state["events"])
        assert not any(event["alertId"] == denied["alertId"] for event in state["events"])
    finally:
        subprocess.check_call(["sudo", "docker", "start", container], stdout=subprocess.DEVNULL)
        stopped = False
        wait_until_ready(config, attempts=40, pause_seconds=2)
    try:
        recovered = {"operatorListening": False}
        for _ in range(10):
            recovered = lab.connect_operator()
            if recovered.get("operatorListening"):
                break
            time.sleep(1)
        assert recovered.get("operatorListening") is True
        assert recovered.get("brokerConnected") is True
        state = lab.snapshot()
        assert state["brokerConnected"] is True
        assert state["operatorListening"] is True
        again = lab.send("heartbeat")
        assert again["outcome"] == "sent"
        assert again["alertId"]
        arrived = False
        for _ in range(20):
            if any(event["alertId"] == again["alertId"] and event["origin"] == "this-session" for event in lab.snapshot()["events"]):
                arrived = True
                break
            time.sleep(0.2)
        assert arrived
    finally:
        lab.close()
        if stopped:
            subprocess.call(["sudo", "docker", "start", container], stdout=subprocess.DEVNULL)


def _wait_event(lab, alert_id, feed, attempts=30):
    found = None
    for _ in range(attempts):
        for event in lab.snapshot()["events"]:
            if event["alertId"] == alert_id and event["feed"] == feed:
                found = event
                break
        if found:
            break
        time.sleep(0.2)
    return found


def test_ground2_heartbeat_stays_off_the_ground1_cards():
    config = _broker_config()
    from solace_demo.catalog import CONSUMER_LAUNCH, CONSUMER_OBJECT, TOPIC_HEARTBEAT_GROUND2, TOPIC_OBJECT_ONLY

    provision(config)
    lab = LiveLab(config)
    lab.open()
    try:
        other = lab.send("heartbeat-ground2")
        assert other["outcome"] == "sent"
        assert other["topic"] == TOPIC_HEARTBEAT_GROUND2
        same = lab.send("heartbeat-ground1")
        plain = lab.send("heartbeat")
        assert same["topic"] == plain["topic"] == TOPIC_OBJECT_ONLY
        ground1_event = _wait_event(lab, same["alertId"], CONSUMER_OBJECT)
        assert ground1_event["origin"] == "this-session"
        assert ground1_event["delivery"] == "direct"
        assert _wait_event(lab, plain["alertId"], CONSUMER_OBJECT)["origin"] == "this-session"
        assert _wait_event(lab, same["alertId"], CONSUMER_LAUNCH, attempts=5) is None
        assert all(event["alertId"] != other["alertId"] for event in lab.snapshot()["events"])
    finally:
        lab.close()


def test_ground2_direct_and_guaranteed_stay_off_the_ground1_object_card():
    config = _broker_config()
    from solace_demo.catalog import TOPIC_DIRECT_GROUND2, TOPIC_DIRECT_ONLY, TOPIC_OTHER_SITE
    from solace_demo.live import display_feed

    provision(config)
    lab = LiveLab(config)
    lab.open()
    try:
        direct = lab.send("direct-live-ground2")
        assert direct["outcome"] == "sent"
        assert direct["brokerAck"] is False
        assert direct["topic"] == TOPIC_DIRECT_GROUND2
        alias = lab.send("direct-live")
        assert alias["topic"] == TOPIC_DIRECT_ONLY
        guaranteed = lab.send("guaranteed-launch-ground2")
        assert guaranteed["outcome"] == "acked"
        assert guaranteed["brokerAck"] is True
        assert guaranteed["topic"] == TOPIC_OTHER_SITE
        same = lab.send("guaranteed-launch-ground1")
        assert same["topic"] == TOPIC_BOTH
        assert same["outcome"] == "acked"
        assert _wait_event(lab, alias["alertId"], "one-object-ground1-25544")["delivery"] == "direct"
        deadline = time.time() + 1.0
        while time.time() < deadline:
            events = lab.snapshot()["events"]
            assert all(event["alertId"] != direct["alertId"] for event in events)
            assert all(
                display_feed(event) != "one-object-ground1-25544" or event["alertId"] != guaranteed["alertId"]
                for event in events
            )
            time.sleep(0.2)
    finally:
        lab.close()


def test_operators_queue_labels_the_backlog_and_a_later_publish_differently():
    config = _broker_config()
    from solace_demo.live import QUEUE_BACKLOG_SECONDS
    from solace_demo.messaging import connect, disconnect, publish_persistent
    from solace_demo.provision import ensure_web_queue

    provision(config)
    ensure_web_queue(Semp(config), config)
    service = connect(config, config.publisher_username, config.publisher_password)
    historical = "history-op-" + str(time.time_ns())
    body = {
        "alertId": historical,
        "alertText": "Launch detected",
        "topic": TOPIC_BOTH,
        "site": "ground1",
        "kind": "launch",
        "objectId": "25544",
    }
    try:
        publish_persistent(service, TOPIC_BOTH, historical, body)
    finally:
        disconnect([service])
    lab = LiveLab(config, role="operators")
    opened = time.monotonic()
    lab.open()
    try:
        found = _wait_event(lab, historical, "broker-queue")
        assert found is not None
        assert found["origin"] == "already-queued"
        assert found["delivery"] == "queued"
        remaining = QUEUE_BACKLOG_SECONDS - (time.monotonic() - opened) + 0.3
        if remaining > 0:
            time.sleep(remaining)
        service = connect(config, config.publisher_username, config.publisher_password)
        live_id = "live-op-" + str(time.time_ns())
        live_body = dict(body)
        live_body["alertId"] = live_id
        try:
            publish_persistent(service, TOPIC_BOTH, live_id, live_body)
        finally:
            disconnect([service])
        arrived = _wait_event(lab, live_id, "broker-queue")
        assert arrived is not None
        assert arrived["origin"] == "this-session"
        assert arrived["delivery"] == "queued"
    finally:
        lab.close()


def test_operators_queue_count_browses_when_semp_is_unset():
    config = _broker_config()
    from solace_demo.catalog import WEB_QUEUE_NAME
    from solace_demo.messaging import connect, disconnect, publish_persistent
    from solace_demo.provision import ensure_web_queue
    from solace_demo.split_client import ClientEndpoint, SplitClient

    provision(config)
    ensure_web_queue(Semp(config), config)
    service = connect(config, config.publisher_username, config.publisher_password)
    waiting = "browse-" + str(time.time_ns())
    body = {
        "alertId": waiting,
        "alertText": "Launch detected",
        "topic": TOPIC_BOTH,
        "site": "ground1",
        "kind": "launch",
        "objectId": "25544",
    }
    try:
        publish_persistent(service, TOPIC_BOTH, waiting, body)
    finally:
        disconnect([service])
    split = SplitClient(
        None,
        ClientEndpoint(
            "operator",
            config.host,
            config.vpn,
            config.subscriber_username,
            config.subscriber_password,
            "",
            False,
        ),
        WEB_QUEUE_NAME,
        "",
        "",
        "",
    )
    assert split.queue_count() is None
    lab = LiveLab(config, split=split, role="operators")
    lab.open()
    try:
        assert lab.snapshot()["queueConfigured"] is True
        assert lab.snapshot()["operatorConnected"] is True
        assert isinstance(lab.snapshot()["queueDepth"], int)
        lab.disconnect_operator()
        assert lab.snapshot()["operatorListening"] is False
        service = connect(config, config.publisher_username, config.publisher_password)
        try:
            publish_persistent(service, TOPIC_BOTH, "browse-held-" + str(time.time_ns()), body)
        finally:
            disconnect([service])
        depth = lab.snapshot()["queueDepth"]
        broker = _message_count(config, WEB_QUEUE_NAME)
        assert depth == broker
        assert depth >= 1
    finally:
        lab.close()


def test_connect_and_disconnect_do_not_overlap_into_two_consumers():
    config = _broker_config()
    from solace_demo.provision import ensure_web_queue

    provision(config)
    ensure_web_queue(Semp(config), config)
    lab = LiveLab(config)
    lab.open()
    try:
        def flip(action: str) -> None:
            if action == "connect":
                lab.connect_operator()
            else:
                lab.disconnect_operator()

        threads = []
        for index in range(8):
            action = "connect" if index % 2 == 0 else "disconnect"
            thread = threading.Thread(target=flip, args=(action,))
            threads.append(thread)
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        lab.disconnect_operator()
        assert lab.snapshot()["operatorListening"] is False
        assert _flows(config, WEB_QUEUE_NAME) == 0
        lab.connect_operator()
        lab.connect_operator()
        assert _flows(config, WEB_QUEUE_NAME) == 1
    finally:
        lab.close()


def test_guaranteed_prefix_stays_off_the_direct_subscriptions():
    config = _broker_config()
    from solace_demo.catalog import LAUNCH_SUBSCRIPTION, alert_body
    from solace_demo.messaging import collect_direct, connect, disconnect, publish_direct, publish_persistent, read_alert_id
    from solace_demo.provision import ensure_topic_exception
    from solace_demo.topics import guaranteed_topic
    from solace.messaging.resources.queue import Queue

    prefix = "ssa-guaranteed/unclass"
    topic = guaranteed_topic(TOPIC_BOTH, prefix)
    queue_name = "q-guaranteed-isolation-test"
    provision(config)
    semp = Semp(config)
    ensure_topic_exception(semp, config, "ssa-publisher-acl", "publish", prefix + "/>")
    queue_body = {
        "queueName": queue_name,
        "accessType": "exclusive",
        "permission": "no-access",
        "ingressEnabled": True,
        "egressEnabled": True,
        "owner": config.subscriber_username,
    }
    try:
        semp.request("POST", f"/SEMP/v2/config/msgVpns/{config.vpn}/queues", queue_body, ok_exists=True)
    except SempError:
        semp.request("PUT", f"/SEMP/v2/config/msgVpns/{config.vpn}/queues/{queue_name}", queue_body)
    semp.request(
        "POST",
        f"/SEMP/v2/config/msgVpns/{config.vpn}/queues/{queue_name}/subscriptions",
        {"subscriptionTopic": prefix + "/>"},
        ok_exists=True,
    )
    guaranteed_id = "g-" + str(time.time_ns())
    direct_id = "d-" + str(time.time_ns())
    publisher = connect(config, config.publisher_username, config.publisher_password)
    subscriber = connect(config, config.subscriber_username, config.subscriber_password)
    found: list = []

    def listen() -> None:
        found.extend(collect_direct(subscriber, LAUNCH_SUBSCRIPTION, 1500))

    try:
        thread = threading.Thread(target=listen)
        thread.start()
        time.sleep(0.4)
        publish_persistent(publisher, topic, guaranteed_id, alert_body(guaranteed_id, topic))
        publish_direct(publisher, TOPIC_BOTH, direct_id, alert_body(direct_id, TOPIC_BOTH))
        thread.join(timeout=5)
        assert guaranteed_id not in found
        assert direct_id in found
        receiver = subscriber.create_persistent_message_receiver_builder().build(
            Queue.durable_exclusive_queue(queue_name)
        )
        receiver.start()
        queued = []
        try:
            while True:
                message = receiver.receive_message(timeout=1000)
                if message is None:
                    break
                queued.append(read_alert_id(message))
                receiver.ack(message)
        finally:
            receiver.terminate()
        assert guaranteed_id in queued
        assert direct_id not in queued
    finally:
        disconnect([publisher, subscriber])
        try:
            semp.request("DELETE", f"/SEMP/v2/config/msgVpns/{config.vpn}/queues/{queue_name}")
        except SempError:
            pass
