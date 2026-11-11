"""Long-lived Solace subscribers for the browser demo.

A direct publish that returns is not a broker acknowledgement. A persistent
acknowledgement is not an operator receipt. Receipts are appended only from
receiver threads, and only after the message has been recorded for display.

The browser binds q-ssa-web-console. It does not bind or acknowledge
q-ssa-operator, so a restart of this process does not drain the quickstart queue.
Messages already waiting on the browser queue are shown as already queued,
then acknowledged. They are not presented as a new click's receipt.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from typing import Any, Optional

from solace.messaging.config.solace_properties import transport_layer_properties
from solace.messaging.resources.queue import Queue
from solace.messaging.resources.topic import Topic
from solace.messaging.resources.topic_subscription import TopicSubscription

from solace_demo.catalog import (
    CONSUMER_WEATHER,
    CONSUMER_LAUNCH,
    CONSUMER_OBJECT,
    LAUNCH_SUBSCRIPTION,
    OBJECT_SUBSCRIPTION,
    WEB_QUEUE_NAME,
    WEATHER_SUBSCRIPTION,
    WEATHER_TOPIC,
    WEATHER_TOPICS,
    TOPIC_BOTH,
    TOPIC_DIRECT_GROUND2,
    TOPIC_DIRECT_ONLY,
    TOPIC_HEARTBEAT_GROUND2,
    TOPIC_OBJECT_ONLY,
    TOPIC_OTHER_SITE,
    alert_body,
)
from solace_demo.config import LabConfig, _merged
from solace_demo.messaging import (
    build_message,
    connect,
    disconnect,
    is_rejection,
    read_alert_id,
    safe_error,
)
from solace_demo.semp import Semp, SempError
from solace_demo.mqtt_weather import WEATHER_TEXT, load_weather, publish_weather, weather_body
from permissions_demo import permission_secret_values, permissions_status
from solace_demo.split_client import (
    demo_broker_label,
    display_broker_label,
    link_status,
    operator_headline,
    path_note,
    peer_name,
)
from solace_demo.topics import guaranteed_topic

SENDS = {
    "launch-ground1": (TOPIC_BOTH, "direct"),
    "launch-ground2": (TOPIC_OTHER_SITE, "direct"),
    "heartbeat": (TOPIC_OBJECT_ONLY, "direct"),
    "heartbeat-ground1": (TOPIC_OBJECT_ONLY, "direct"),
    "heartbeat-ground2": (TOPIC_HEARTBEAT_GROUND2, "direct"),
    "guaranteed-launch": (TOPIC_BOTH, "guaranteed"),
    "guaranteed-launch-ground1": (TOPIC_BOTH, "guaranteed"),
    "guaranteed-launch-ground2": (TOPIC_OTHER_SITE, "guaranteed"),
    "direct-live": (TOPIC_DIRECT_ONLY, "direct"),
    "direct-live-ground1": (TOPIC_DIRECT_ONLY, "direct"),
    "direct-live-ground2": (TOPIC_DIRECT_GROUND2, "direct"),
}

# Queue messages already spooled at bind arrive before this window ends.
QUEUE_BACKLOG_SECONDS = 1.0

# Short timeouts so a stopped broker fails closed. These are SDK 1.11 keys.
# with_max_unacked_messages is a 1.12 builder method and is not used.
WEB_TRANSPORT = {
    transport_layer_properties.CONNECTION_RETRIES: 0,
    transport_layer_properties.RECONNECTION_ATTEMPTS: 0,
    transport_layer_properties.CONNECTION_ATTEMPTS_TIMEOUT: 3000,
}

DIRECT_CUSTOMER_TEXT = (
    "Sent. The operator shows this alert when the same id arrives. "
    "A broker ACK is a separate result."
)
GUARANTEED_CUSTOMER_TEXT = (
    "The broker acknowledged this alert. "
    "The operator shows it when the same id arrives."
)
LOCAL_DOWN_TEXT = (
    "The local lab broker is not answering. This console is not receiving. Press Connect to try again."
)
LOCAL_SEND_BLOCKED = "The local lab broker is not connected. Nothing was sent."
LOCAL_SUBSCRIBE_BLOCKED = "The local lab broker is not connected. Nothing was changed."


def ground1_object_25544(topic: str) -> bool:
    """Topic site is ground 1 and the object id is 25544.

    Direct topics and guaranteed topics both use two levels before the site,
    so ground1 is parts[2] and 25544 is parts[4].
    """
    parts = [part for part in str(topic or "").split("/") if part]
    return len(parts) >= 5 and parts[2] == "ground1" and parts[4] == "25544"


def display_feed(event: dict) -> str:
    """Which operator card shows this receipt.

    Queued receipts join the Ground 1 object card only when the topic is that
    object. Other queued receipts stay off every card.
    """
    if event.get("feed") == "broker-queue" or event.get("delivery") == "queued":
        if ground1_object_25544(str(event.get("topic") or "")):
            return CONSUMER_OBJECT
        return ""
    return str(event.get("feed") or "")


def waiting_message_count(payload: dict, page_limit: int = 100) -> Optional[int]:
    """How many messages the broker still lists on the queue.

    On this broker image, queue spooledMsgCount stayed above zero after the
    consumer had acknowledged the message and the message list was empty.
    The list is the observation the page shows. A full page is not an exact
    total, so that case returns None instead of a guessed number.
    """
    if not isinstance(payload, dict):
        return None
    meta = payload.get("meta")
    data = payload.get("data")
    if not isinstance(meta, dict) or not isinstance(data, list):
        return None
    count = meta.get("count")
    if isinstance(count, bool) or not isinstance(count, int):
        return None
    if count != len(data) or count >= page_limit:
        return None
    return count


def plan_send(kind: str, guaranteed_prefix: str, split_mode: bool) -> dict:
    """Choose the topic. Direct topics never move. Split guaranteed needs a prefix."""
    topic, delivery = SENDS[kind]
    if delivery != "guaranteed":
        return {"topic": topic, "delivery": delivery, "blocked": False}
    if split_mode and not guaranteed_prefix:
        return {"topic": topic, "delivery": delivery, "blocked": True}
    if guaranteed_prefix:
        topic = guaranteed_topic(topic, guaranteed_prefix)
    return {"topic": topic, "delivery": delivery, "blocked": False}


def publish_outcome(delivery: str) -> dict:
    """Local send result. Direct return is not an acknowledgement."""
    if delivery == "direct":
        return {
            "outcome": "sent",
            "sendReturned": True,
            "brokerAck": False,
            "detail": "direct publish returned",
            "customerText": DIRECT_CUSTOMER_TEXT,
        }
    if delivery == "guaranteed":
        return {
            "outcome": "acked",
            "sendReturned": True,
            "brokerAck": True,
            "detail": "persistent publish acknowledgement",
            "customerText": GUARANTEED_CUSTOMER_TEXT,
        }
    raise ValueError("unknown delivery")


def not_sent(customer_text: str, detail: str = "") -> dict:
    return {
        "outcome": "not-sent",
        "sendReturned": False,
        "brokerAck": False,
        "brokerAccepted": False,
        "alertId": "",
        "detail": detail or customer_text,
        "customerText": customer_text,
    }


def refused(detail: str, customer_text: str, alert_id: str = "", topic: str = "", alert_text: str = "", delivery: str = "") -> dict:
    result = {
        "outcome": "refused",
        "sendReturned": False,
        "brokerAck": False,
        "brokerAccepted": False,
        "alertId": alert_id,
        "detail": detail,
        "customerText": customer_text,
    }
    if topic:
        result["topic"] = topic
    if alert_text:
        result["alertText"] = alert_text
    if delivery:
        result["delivery"] = delivery
    return result


def receipt_matches(active_id: str, active_seq: str, watch_seq: str, event: dict) -> bool:
    """A receipt line may mention only the alert still shown for that request.

    An older watch must not attach its text to a later send, and a message
    that was already on the queue is not a receipt for this click.
    """
    if not active_id or str(active_seq) != str(watch_seq):
        return False
    if not isinstance(event, dict):
        return False
    return event.get("alertId") == active_id and event.get("origin") == "this-session"


def customer_refusal(detail: str) -> str:
    if "SOLCLIENT_SUBCODE_PUBLISH_ACL_DENIED" in detail:
        return "The broker refused to send this alert."
    if "SOLCLIENT_SUBCODE_SUBSCRIPTION_ACL_DENIED" in detail:
        return "The broker refused that subscription."
    return "The broker did not accept this request."


def _body_from_message(message) -> dict:
    raw = message.get_payload_as_string() or ""
    if not raw:
        try:
            blob = message.get_payload_as_bytes()
        except Exception:
            blob = b""
        if blob:
            raw = bytes(blob).decode("utf-8")
    try:
        body = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        body = {}
    if not isinstance(body, dict):
        body = {}
    if not body.get("topic"):
        try:
            body["topic"] = message.get_destination_name() or ""
        except Exception:
            body["topic"] = ""
    if not body.get("alertId"):
        body["alertId"] = read_alert_id(message)
    return body


class LiveLab:
    def __init__(self, config: LabConfig, split=None, role: str = "all"):
        self.config = config
        self.split = split
        self.role = role if role in {"all", "publisher", "operators"} else "all"
        self.guaranteed_prefix = split.guaranteed_prefix if split is not None else ""
        self.weather = load_weather()
        self.broker_connected = False
        self.listening = False
        self.receiver_failed = False
        self.guaranteed_available = False
        self.guaranteed_bind_error = ""
        self.last_error = ""
        self._lock = threading.Lock()
        self._session_lock = threading.Lock()
        self._events: list[dict] = []
        self._published: dict[str, dict] = {}
        self._generation = 0
        self._threads: list[threading.Thread] = []
        self._receivers: list[Any] = []
        self._publisher = None
        self._subscriber = None
        self._direct_publisher = None
        self._guaranteed_publisher = None
        self._publish_lock = threading.Lock()
        self._async_fail = ""
        self._probed_at = 0.0
        self._depth_cache: Optional[tuple] = None

    def open(self) -> None:
        with self._session_lock:
            try:
                self._open_sessions_locked()
                if self.role != "publisher":
                    self._listen_locked()
            except Exception:
                self._stop_receivers_locked()
                self._close_sessions_locked()
                self.broker_connected = False
                self.listening = False
                raise

    def close(self) -> None:
        with self._session_lock:
            self._close_sessions_locked()

    def connect_operator(self) -> dict:
        with self._session_lock:
            if not self._semp_up():
                self._stop_receivers_locked()
                self._close_sessions_locked()
                self.broker_connected = False
                self.receiver_failed = True
                self.last_error = LOCAL_DOWN_TEXT
                return {
                    "ok": False,
                    "operatorListening": False,
                    "brokerConnected": False,
                    "receiverFailed": True,
                    "customerText": LOCAL_DOWN_TEXT,
                }
            if not self._sessions_report_connected():
                try:
                    self._open_sessions_locked()
                except Exception as exc:
                    detail = safe_error(exc)
                    self._close_sessions_locked()
                    self.broker_connected = False
                    self.receiver_failed = True
                    self.last_error = detail
                    return {
                        "ok": False,
                        "operatorListening": False,
                        "brokerConnected": False,
                        "receiverFailed": True,
                        "customerText": self._down_text(),
                        "detail": detail,
                    }
            if self.listening and self._receivers and not self.receiver_failed:
                return {
                    "ok": True,
                    "operatorListening": True,
                    "brokerConnected": True,
                    "receiverFailed": False,
                    "customerText": "Already connected.",
                }
            try:
                self._listen_locked()
            except Exception as exc:
                self._stop_receivers_locked()
                self.receiver_failed = True
                self.last_error = safe_error(exc)
                return {
                    "ok": False,
                    "operatorListening": False,
                    "brokerConnected": self.broker_connected,
                    "receiverFailed": True,
                    "customerText": "This console's receiver stopped. The Solace session is still up. Press Connect to try again.",
                    "detail": self.last_error,
                }
            return {
                "ok": True,
                "operatorListening": True,
                "brokerConnected": True,
                "receiverFailed": False,
                "customerText": "Connected to the broker.",
            }

    def disconnect_operator(self) -> dict:
        with self._session_lock:
            self._stop_receivers_locked()
            self.receiver_failed = False
            self.listening = False
            connected = self.broker_connected
        return {
            "ok": True,
            "operatorListening": False,
            "brokerConnected": connected,
            "receiverFailed": False,
            "customerText": "Disconnected. Queued alerts stay on the broker until Connect.",
        }

    def note_broker_down(self, detail: str) -> None:
        with self._session_lock:
            already = (not self.broker_connected) and (not self.listening) and (not self._receivers)
            self.broker_connected = False
            self.last_error = (detail or self._down_text())[:240]
            self._depth_cache = None
            self.receiver_failed = True
            if already:
                return
            self._stop_receivers_locked()

    def secret_values(self) -> list:
        values = [
            self.config.admin_password,
            self.config.publisher_password,
            self.config.subscriber_password,
        ]
        if self.split is not None:
            values.extend(self.split.secrets())
        if self.weather.password:
            values.append(self.weather.password)
        values.extend(permission_secret_values())
        return [item for item in values if item]

    def _open_sessions_locked(self) -> None:
        self._close_sessions_locked()
        if self.split is None:
            publisher_user = self.config.publisher_username
            publisher_password = self.config.publisher_password
            subscriber_user = self.config.subscriber_username
            subscriber_password = self.config.subscriber_password
            publisher_props = WEB_TRANSPORT
            subscriber_props = WEB_TRANSPORT
        else:
            publisher_user = self.split.publisher.username if self.split.publisher is not None else ""
            publisher_password = self.split.publisher.password if self.split.publisher is not None else ""
            subscriber_user = self.split.operator.username if self.split.operator is not None else ""
            subscriber_password = self.split.operator.password if self.split.operator is not None else ""
            publisher_props = self.split.publisher.client_properties() if self.split.publisher is not None else WEB_TRANSPORT
            subscriber_props = self.split.operator.client_properties() if self.split.operator is not None else WEB_TRANSPORT
        self._publisher = None
        self._subscriber = None
        if self.role != "operators":
            self._publisher = connect(self.config, publisher_user, publisher_password, publisher_props)
        if self.role != "publisher":
            self._subscriber = connect(self.config, subscriber_user, subscriber_password, subscriber_props)
        self._direct_publisher = None
        self._guaranteed_publisher = None
        if self._publisher is not None:
            self._ensure_publishers()
        self.broker_connected = True
        self.receiver_failed = False
        self.last_error = ""
        self._async_fail = ""

    def _close_sessions_locked(self) -> None:
        self._stop_receivers_locked()
        for publisher in (self._direct_publisher, self._guaranteed_publisher):
            if publisher is None:
                continue
            try:
                publisher.terminate()
            except Exception:
                pass
        self._direct_publisher = None
        self._guaranteed_publisher = None
        disconnect([item for item in (self._publisher, self._subscriber) if item is not None])
        self._publisher = None
        self._subscriber = None
        self.broker_connected = False

    def _role_services(self) -> tuple:
        if self.role == "publisher":
            return (self._publisher,)
        if self.role == "operators":
            return (self._subscriber,)
        return (self._publisher, self._subscriber)

    def _sessions_report_connected(self) -> bool:
        for service in self._role_services():
            if service is None:
                return False
            try:
                connected = service.is_connected
            except Exception:
                return False
            if not connected:
                return False
        return True

    def _semp_up(self) -> bool:
        if self.split is not None:
            return True
        try:
            Semp(self.config, timeout=1.0).request("GET", "/SEMP/v2/config/about")
        except (SempError, OSError, TimeoutError):
            return False
        return True

    def _queue_name(self) -> str:
        if self.split is not None:
            return self.split.operator_queue
        return WEB_QUEUE_NAME

    def _ensure_publishers(self) -> None:
        with self._publish_lock:
            if self._direct_publisher is None:
                self._direct_publisher = self._publisher.create_direct_message_publisher_builder().build()
                self._direct_publisher.start()
            if self._guaranteed_publisher is None:
                self._guaranteed_publisher = (
                    self._publisher.create_persistent_message_publisher_builder().on_back_pressure_reject(10).build()
                )
                self._guaranteed_publisher.start()

    def _publish(self, topic: str, alert_id: str, body: dict, delivery: str) -> None:
        self._ensure_publishers()
        message = build_message(self._publisher, alert_id, body)
        destination = Topic.of(topic)
        with self._publish_lock:
            if delivery == "direct":
                self._direct_publisher.publish(message, destination)
                return
            self._guaranteed_publisher.publish_await_acknowledgement(message, destination, time_out=5000)

    def _listen_locked(self) -> None:
        if not self.broker_connected or self._subscriber is None:
            raise RuntimeError("Lab broker is not connected.")
        self._stop_receivers_locked()
        generation = self._generation
        specs = [
            (CONSUMER_LAUNCH, LAUNCH_SUBSCRIPTION, False),
            (CONSUMER_OBJECT, OBJECT_SUBSCRIPTION, False),
        ]
        if self.weather.enabled:
            specs.append((CONSUMER_WEATHER, WEATHER_SUBSCRIPTION, False))
        try:
            for feed, subscription, queue in specs:
                self._start_thread(generation, feed, subscription, queue)
        except Exception:
            self._stop_receivers_locked()
            raise
        self.listening = True
        self.receiver_failed = False
        self.guaranteed_available = False
        self.guaranteed_bind_error = ""
        queue_name = self._queue_name()
        if not queue_name:
            return
        try:
            self._start_thread(generation, "broker-queue", None, True)
        except Exception as exc:
            from solace_demo.provision import broker_is_remote

            if self.split is None and not broker_is_remote(self.config):
                self._stop_receivers_locked()
                raise
            self.guaranteed_available = False
            self.guaranteed_bind_error = safe_error(exc)
            return
        self.guaranteed_available = True

    def _start_thread(self, generation: int, feed: str, subscription: Optional[str], queue: bool) -> None:
        receiver = self._start_receiver(subscription, queue)
        self._receivers.append(receiver)
        thread = threading.Thread(
            target=self._receive_loop,
            args=(generation, feed, receiver, queue),
            name=f"solace-{feed}",
            daemon=True,
        )
        self._threads.append(thread)
        thread.start()

    def _stop_receivers_locked(self) -> None:
        self._generation += 1
        self.listening = False
        receivers = list(self._receivers)
        threads = list(self._threads)
        self._receivers = []
        self._threads = []
        for receiver in receivers:
            try:
                receiver.terminate()
            except Exception:
                pass
        for thread in threads:
            if thread is threading.current_thread():
                continue
            thread.join(timeout=2)

    def _start_receiver(self, subscription: Optional[str], queue: bool):
        if queue:
            receiver = self._subscriber.create_persistent_message_receiver_builder().build(
                Queue.durable_exclusive_queue(self._queue_name())
            )
        else:
            receiver = (
                self._subscriber.create_direct_message_receiver_builder()
                .with_subscriptions([TopicSubscription.of(subscription)])
                .build()
            )
        receiver.start()
        return receiver

    def _receive_loop(self, generation: int, feed: str, receiver, queue: bool) -> None:
        drain_until = time.monotonic() + QUEUE_BACKLOG_SECONDS if queue else 0.0
        while generation == self._generation:
            draining = bool(queue) and time.monotonic() < drain_until
            try:
                message = receiver.receive_message(timeout=400)
            except Exception as exc:
                self._async_fail = safe_error(exc)
                break
            if message is None:
                continue
            if generation != self._generation:
                break
            redelivered = False
            if queue:
                try:
                    redelivered = bool(message.is_redelivered())
                except Exception:
                    redelivered = False
            body = _body_from_message(message)
            recorded, should_ack = self._record(
                generation,
                feed,
                body,
                queue=queue,
                redelivered=redelivered,
                draining=draining,
            )
            if queue and recorded and should_ack:
                try:
                    receiver.ack(message)
                except Exception as exc:
                    self._async_fail = safe_error(exc)
                    break

    def _record(
        self,
        generation: int,
        feed: str,
        body: dict,
        queue: bool = False,
        redelivered: bool = False,
        draining: bool = False,
    ) -> tuple:
        alert_id = str(body.get("alertId") or "")
        with self._lock:
            if generation != self._generation:
                return False, False
            origin = self._origin(alert_id, queue=queue, redelivered=redelivered, draining=draining)
            self._events.append(
                {
                    "alertId": alert_id,
                    "alertText": body.get("alertText") or "",
                    "topic": body.get("topic") or "",
                    "site": body.get("site") or "",
                    "kind": body.get("kind") or "",
                    "feed": feed,
                    "delivery": "queued" if queue else "direct",
                    "origin": origin,
                    "receivedAt": time.time(),
                }
            )
            # The operators console acknowledges what it shows. A combined split
            # process still leaves a message it did not publish on the broker.
            if self.role == "operators":
                should_ack = True
            else:
                should_ack = not (self.split is not None and origin == "already-queued")
            return True, should_ack

    def clear_display(self, feed: str) -> dict:
        """Drop one card's receipts from this page. The broker queue is left as it is."""
        if feed not in {CONSUMER_LAUNCH, CONSUMER_OBJECT, CONSUMER_WEATHER}:
            raise ValueError("unknown feed")
        with self._lock:
            self._events = [event for event in self._events if display_feed(event) != feed]
        return {"ok": True, "feed": feed}

    def _origin(self, alert_id: str, queue: bool, redelivered: bool, draining: bool) -> str:
        if alert_id and alert_id in self._published:
            return "this-session"
        if self.role == "operators":
            if queue and (draining or redelivered):
                return "already-queued"
            return "this-session"
        return "already-queued"

    def _observe(self) -> None:
        if self._async_fail:
            detail = self._async_fail
            self._async_fail = ""
            self.note_broker_down(detail)
            return
        if self._publisher is None and self._subscriber is None:
            self.broker_connected = False
            return
        now = time.time()
        if now - self._probed_at < 1.0:
            return
        self._probed_at = now
        if not self._sessions_report_connected() or not self._semp_up():
            self.note_broker_down(self._down_text())

    def send(self, kind: str) -> dict:
        if kind == "weather":
            return self._send_weather("ground1")
        if kind.startswith("weather-") and kind[len("weather-"):] in WEATHER_TOPICS:
            return self._send_weather(kind[len("weather-"):])
        if kind not in SENDS:
            raise ValueError("unknown send")
        self._observe()
        if not self.broker_connected or self._publisher is None or not self._semp_up():
            if self.broker_connected:
                self.note_broker_down(self._down_text())
            return not_sent(self._send_blocked_text())
        plan = plan_send(kind, self.guaranteed_prefix, self.split is not None)
        topic, delivery = plan["topic"], plan["delivery"]
        if plan["blocked"] or (delivery == "guaranteed" and not self._guaranteed_ready()):
            note = self._guaranteed_note()
            return not_sent(note, note)
        alert_id = "ex-" + uuid.uuid4().hex[:10]
        body = alert_body(alert_id, topic)
        with self._lock:
            self._published[alert_id] = {"topic": topic, "delivery": delivery, "kind": kind}
        try:
            self._publish(topic, alert_id, body, delivery)
        except Exception as exc:
            with self._lock:
                self._published.pop(alert_id, None)
            detail = safe_error(exc)
            if is_rejection(exc):
                return refused(detail, customer_refusal(detail), alert_id, topic, body["alertText"], delivery)
            self.note_broker_down(detail)
            return not_sent("The broker did not take this alert. Nothing new was received.", detail)
        result = publish_outcome(delivery)
        result.update(
            {
                "alertId": alert_id,
                "topic": topic,
                "alertText": body["alertText"],
                "delivery": delivery,
            }
        )
        return result

    def snapshot(self) -> dict:
        self._observe()
        depth = self.queue_depth()
        with self._session_lock:
            connected = self.broker_connected
            listening = self.listening
            failed = self.receiver_failed
            last_error = self.last_error
        if not connected:
            depth = None
        with self._lock:
            events = list(self._events)
        if self.split is None:
            mode = "local-lab"
            mode_label = ""
            publisher_host = self.config.host
            operator_host = self.config.host
            publisher_name = "local lab broker"
            operator_name = "local lab broker"
            queue_name = WEB_QUEUE_NAME
            publisher_vpn = self.config.vpn
            operator_vpn = self.config.vpn
        else:
            mode = "split-client"
            mode_label = self.split.mode_label()
            if self.split.publisher is not None:
                publisher_host = self.split.publisher.host
                publisher_name = peer_name(publisher_host, "publisher")
                publisher_vpn = self.split.publisher.vpn
                publisher_client = self.split.publisher.username
            else:
                publisher_host = ""
                publisher_name = ""
                publisher_vpn = ""
                publisher_client = ""
            if self.split.operator is not None:
                operator_host = self.split.operator.host
                operator_name = peer_name(operator_host, "operator")
                operator_vpn = self.split.operator.vpn
                operator_client = self.split.operator.username
                queue_name = self.split.operator_queue
            else:
                operator_host = ""
                operator_name = ""
                operator_vpn = ""
                operator_client = ""
                queue_name = ""
        publisher_endpoint = _host_port_only(publisher_host) if publisher_host else ""
        operator_endpoint = _host_port_only(operator_host) if operator_host else ""
        if self.split is None:
            publisher_client = self.config.publisher_username
            operator_client = self.config.subscriber_username
        operator_broker = demo_broker_label(operator_host) if operator_host else ""
        publisher_broker = demo_broker_label(publisher_host) if publisher_host else ""
        primary_path = (
            primary_operator_path(self.split is not None, operator_broker, publisher_broker)
            if operator_host and publisher_host
            else ""
        )
        operator_connected = bool(connected and listening and not failed)
        queue_configured = bool(queue_name)
        both_loopback = bool(publisher_host and operator_host and _is_loopback_host(publisher_host) and _is_loopback_host(operator_host))
        auth_note = ""
        if self.split is not None and self.split.operator is not None and self.split.operator.passwordless:
            auth_note = "Operator authentication: none. Not an ACL or identity proof."
        return {
            "brokerConnected": connected,
            "operatorListening": listening if connected else False,
            "operatorConnected": operator_connected,
            "receiverFailed": failed,
            "webRole": self.role,
            "mode": mode,
            "modeLabel": mode_label,
            "guaranteedAvailable": self._guaranteed_ready() if connected else False,
            "guaranteedTopic": plan_send("guaranteed-launch", self.guaranteed_prefix, self.split is not None)["topic"],
            "guaranteedNote": self._guaranteed_note(),
            "weatherEnabled": self.weather.enabled,
            "weatherTopic": WEATHER_TOPIC if self.weather.enabled else "",
            "weatherSubscription": WEATHER_SUBSCRIPTION if self.weather.enabled else "",
            "weatherTarget": self.weather.target() if self.weather.enabled else "",
            "weatherProblem": self.weather.problem,
            **permissions_status(),
            "vpn": operator_vpn,
            "smfHost": operator_endpoint,
            "publisherEndpoint": publisher_endpoint,
            "operatorEndpoint": operator_endpoint,
            "publisherName": publisher_name,
            "operatorName": operator_name,
            "publisherClient": publisher_client,
            "primaryOperatorClient": operator_client,
            "primaryOperatorBroker": operator_broker,
            "operatorBrokerLabel": display_broker_label(
                operator_host, _merged("SOLACE_OPERATOR_BROKER_LABEL", "")
            ) if operator_host else "",
            "primaryOperatorPath": primary_path,
            "publisherStatus": link_status(publisher_name, connected) if publisher_name else "",
            "operatorStatus": operator_headline(
                operator_name, connected, bool(listening) and connected, failed
            ) if operator_name else "",
            "publisherDetail": f"{publisher_endpoint} · VPN {publisher_vpn}",
            "operatorDetail": f"{operator_endpoint} · VPN {operator_vpn}",
            "pathNote": (
                path_note(self.split is not None, publisher_name, operator_name, both_loopback)
                if publisher_name and operator_name
                else (f"Publisher is {publisher_name}." if publisher_name else (f"Operator is the {operator_name}." if operator_name else ""))
            ),
            "authNote": auth_note,
            "connectDisabled": operator_connected,
            "disconnectDisabled": not operator_connected,
            "queueConfigured": queue_configured,
            "events": events,
            "queueDepth": depth,
            "queueName": queue_name,
            "lastError": last_error,
        }

    def _endpoint_up(self, service) -> bool:
        if service is None:
            return False
        try:
            return bool(service.is_connected)
        except Exception:
            return False

    def _down_text(self) -> str:
        if self.split is None:
            return LOCAL_DOWN_TEXT
        if self.split.publisher is None or self.split.operator is None:
            endpoint = self.split.publisher or self.split.operator
            name = peer_name(endpoint.host, "publisher" if self.split.publisher is not None else "operator")
            if self.role == "operators":
                return f"The {name} session stopped. Press Connect to try again."
            return f"The {name} session stopped."
        publisher_name = peer_name(self.split.publisher.host, "publisher")
        operator_name = peer_name(self.split.operator.host, "operator")
        publisher_up = self._endpoint_up(self._publisher)
        operator_up = self._endpoint_up(self._subscriber)
        if publisher_up and not operator_up:
            return (
                f"The {operator_name} session stopped. This console is not receiving. "
                "Press Connect to try again."
            )
        if operator_up and not publisher_up:
            return (
                f"The {publisher_name} session stopped. This console is not receiving. "
                "Press Connect to try again."
            )
        return (
            f"This console is not receiving. The {publisher_name} session or the {operator_name} session stopped. "
            "Press Connect to try again."
        )

    def _send_blocked_text(self) -> str:
        if self.split is None:
            return LOCAL_SEND_BLOCKED
        return "A Solace session is down. Nothing was sent."

    def _subscribe_blocked_text(self) -> str:
        if self.split is None:
            return LOCAL_SUBSCRIBE_BLOCKED
        return "A Solace session is down. Nothing was changed."

    def _send_weather(self, site: str = "ground1") -> dict:
        topic = WEATHER_TOPICS[site]
        if not self.weather.enabled:
            text = self.weather.problem or "The simulated weather example is off."
            return not_sent(text, text)
        alert_id = "wx-" + uuid.uuid4().hex[:10]
        body = weather_body(alert_id, topic)
        with self._lock:
            self._published[alert_id] = {"topic": topic, "delivery": "mqtt-qos0", "kind": "weather"}
        try:
            publish_weather(self.weather, alert_id, body, topic)
        except Exception as exc:
            with self._lock:
                self._published.pop(alert_id, None)
            detail = safe_error(exc)
            return not_sent("The MQTT publish did not leave this process. Nothing was received.", detail)
        return {
            "outcome": "sent",
            "sendReturned": True,
            "brokerAck": False,
            "alertId": alert_id,
            "topic": topic,
            "alertText": body["alertText"],
            "delivery": "mqtt-qos0",
            "detail": "mqtt qos 0 publish handed to the socket",
            "customerText": WEATHER_TEXT,
        }

    def _guaranteed_ready(self) -> bool:
        if self.role == "publisher":
            return bool(self.guaranteed_prefix) and self._endpoint_up(self._publisher)
        if not self.guaranteed_available:
            return False
        if self.split is not None and not self.guaranteed_prefix:
            return False
        return True

    def _guaranteed_note(self) -> str:
        if self.role == "publisher":
            if not self.guaranteed_prefix:
                return "Guaranteed alerts stay off until SOLACE_GUARANTEED_TOPIC_PREFIX is set."
            topic = guaranteed_topic(TOPIC_BOTH, self.guaranteed_prefix)
            return f"Topic {topic}. A broker ACK means the broker accepted it."
        if self.split is not None:
            if self.guaranteed_bind_error:
                return (
                    "The operator queue could not be bound. Guaranteed controls are off. "
                    "The queue was not created or cleared."
                )
            return self.split.guaranteed_note()
        if self.guaranteed_prefix:
            topic = guaranteed_topic(TOPIC_BOTH, self.guaranteed_prefix)
            return f"Guaranteed alerts use {topic}. Direct alerts stay on ssa/unclass/."
        return ""

    def queue_depth(self) -> Optional[int]:
        if self.split is not None:
            if not self.broker_connected:
                return None
            counted = self.split.queue_count()
            if counted is not None:
                return counted
            return self._browse_queue_count()
        with self._session_lock:
            if not self.broker_connected:
                return None
            cached = self._depth_cache
        now = time.time()
        if cached is not None and now - cached[0] < 0.4:
            return cached[1]
        try:
            payload = Semp(self.config, timeout=1.0).request(
                "GET",
                f"/SEMP/v2/monitor/msgVpns/{self.config.vpn}/queues/{WEB_QUEUE_NAME}/msgs?count=100",
            )
        except (SempError, OSError, TimeoutError):
            self.note_broker_down(LOCAL_DOWN_TEXT)
            return None
        count = waiting_message_count(payload)
        if count is None:
            return None
        with self._session_lock:
            self._depth_cache = (now, count)
        return count

    def _browse_queue_count(self) -> Optional[int]:
        """Count messages on the operator queue without removing them.

        Used when the operators process has the queue name and no SEMP settings.
        The browser flow does not acknowledge and does not call remove.
        """
        queue_name = self._queue_name()
        service = self._subscriber
        if not queue_name or service is None:
            return None
        browser = None
        try:
            browser = service.create_message_queue_browser_builder().build(
                Queue.durable_exclusive_queue(queue_name)
            )
            browser.start()
            count = 0
            while count < 100:
                message = browser.receive_message(timeout=200 if count == 0 else 0)
                if message is None:
                    return count
                count += 1
            return None
        except Exception:
            return None
        finally:
            if browser is not None:
                try:
                    browser.terminate()
                except Exception:
                    pass


def primary_operator_path(split_mode: bool, operator_broker: str, publisher_broker: str) -> str:
    """Who the Primary Operator receives from."""
    if not split_mode:
        return (
            "Receives on " + operator_broker + ". "
            "The publisher uses this same broker with a different client."
        )
    if operator_broker == "my local Solace broker" and publisher_broker == "my Solace Cloud broker":
        return (
            "Receives on " + operator_broker + ". "
            "The publisher uses a different client on " + publisher_broker + ". "
            "Bridge to-cloud-unclass carries alerts to the operator broker."
        )
    if operator_broker == "my local Solace broker" and publisher_broker == "my local Solace broker":
        return (
            "Receives on " + operator_broker + ". "
            "The publisher uses " + publisher_broker + "."
        )
    return (
        "Receives on " + operator_broker + ". "
        "The publisher uses a different client on " + publisher_broker + "."
    )


def _is_loopback_host(host: str) -> bool:
    from urllib.parse import urlparse

    parsed = urlparse(host if "://" in host else f"tcp://{host}")
    return (parsed.hostname or "").lower() in {"127.0.0.1", "localhost", "::1"}


def _host_only(host: str) -> str:
    if "://" in host:
        parsed = host.split("://", 1)[1]
        return parsed
    return host


def _host_port_only(host: str) -> str:
    text = _host_only(host)
    if "@" in text:
        text = text.split("@", 1)[1]
    return text
