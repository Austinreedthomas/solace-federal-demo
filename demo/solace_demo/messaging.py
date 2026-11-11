"""Solace Python API sessions. Payloads are strings. Passwords are not logged."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable

from solace.messaging.config.solace_properties import (
    authentication_properties,
    client_properties,
    message_properties,
    service_properties,
    transport_layer_properties,
)
from solace.messaging.config.solace_properties.transport_layer_security_properties import TRUST_STORE_PATH
from solace.messaging.config.transport_security_strategy import TLS
from solace.messaging.errors.pubsubplus_client_error import (
    MessageRejectedByBrokerError,
    PubSubPlusClientError,
)
from solace.messaging.messaging_service import MessagingService
from solace.messaging.resources.queue import Queue
from solace.messaging.resources.topic import Topic
from solace.messaging.resources.topic_subscription import TopicSubscription

from solace_demo.catalog import QUEUE_NAME
from solace_demo.config import LabConfig, publisher_client_name


class MessagingError(RuntimeError):
    pass


def with_publisher_client_name(properties: dict | None = None) -> dict:
    """Set solace.messaging.client.name when SOLACE_CLIENT_NAME is present.

    When the variable is unset or blank, the property is omitted so the API
    auto-generates a client name.
    """
    values = dict(properties or {})
    name = publisher_client_name()
    if name:
        values[client_properties.NAME] = name
    return values


def connect(config: LabConfig, username: str, password: str, properties: dict | None = None) -> MessagingService:
    values = {
        transport_layer_properties.HOST: config.host,
        service_properties.VPN_NAME: config.vpn,
        authentication_properties.SCHEME_BASIC_USER_NAME: username,
        authentication_properties.SCHEME_BASIC_PASSWORD: password,
    }
    if properties:
        values.update(properties)
    host = str(values.get(transport_layer_properties.HOST, ""))
    if host.lower().startswith("tcps://") and TRUST_STORE_PATH not in values:
        trust = os.environ.get("SOLACE_PUBLISHER_TRUST_STORE", "").strip()
        if trust and Path(trust).is_dir():
            values.update(TLS.create().with_certificate_validation(False, True, trust).security_configuration)
    service = MessagingService.builder().from_properties(values).build()
    service.connect()
    return service


def build_message(service: MessagingService, alert_id: str, body: dict):
    encoded = json.dumps(body, separators=(",", ":"), sort_keys=True)
    return (
        service.message_builder()
        .from_properties(
            {
                message_properties.APPLICATION_MESSAGE_ID: alert_id,
                message_properties.CORRELATION_ID: alert_id,
                message_properties.SENDER_ID: "synthetic-satellite-publisher",
            }
        )
        .build(encoded)
    )


def read_alert_id(message) -> str:
    correlation = message.get_correlation_id()
    if correlation:
        return str(correlation)
    payload = message.get_payload_as_string() or ""
    try:
        return str(json.loads(payload).get("alertId") or "")
    except json.JSONDecodeError:
        return ""


def publish_direct(service: MessagingService, topic: str, alert_id: str, body: dict) -> None:
    publisher = service.create_direct_message_publisher_builder().build()
    publisher.start()
    try:
        publisher.publish(build_message(service, alert_id, body), Topic.of(topic))
    finally:
        publisher.terminate()


def publish_persistent(service: MessagingService, topic: str, alert_id: str, body: dict) -> str:
    """Return 'acked' or raise MessageRejectedByBrokerError / PubSubPlusClientError."""
    publisher = (
        service.create_persistent_message_publisher_builder().on_back_pressure_reject(10).build()
    )
    publisher.start()
    try:
        publisher.publish_await_acknowledgement(
            build_message(service, alert_id, body),
            Topic.of(topic),
            time_out=5000,
        )
    finally:
        publisher.terminate()
    return "acked"


def collect_direct(service: MessagingService, subscription: str, wait_ms: int) -> list[str]:
    receiver = (
        service.create_direct_message_receiver_builder()
        .with_subscriptions([TopicSubscription.of(subscription)])
        .build()
    )
    receiver.start()
    found: list[str] = []
    try:
        while True:
            message = receiver.receive_message(timeout=wait_ms)
            if message is None:
                break
            found.append(read_alert_id(message))
            wait_ms = 200
    finally:
        receiver.terminate()
    return found


def try_subscribe(service: MessagingService, subscription: str) -> str:
    receiver = service.create_direct_message_receiver_builder().build()
    receiver.start()
    try:
        receiver.add_subscription(TopicSubscription.of(subscription))
        return "accepted"
    finally:
        receiver.terminate()


def receive_guaranteed(service: MessagingService, wait_ms: int) -> list[str]:
    queue = Queue.durable_exclusive_queue(QUEUE_NAME)
    receiver = service.create_persistent_message_receiver_builder().build(queue)
    receiver.start()
    found: list[str] = []
    try:
        while True:
            message = receiver.receive_message(timeout=wait_ms)
            if message is None:
                break
            found.append(read_alert_id(message))
            receiver.ack(message)
            wait_ms = 200
    finally:
        receiver.terminate()
    return found


def safe_error(exc: BaseException) -> str:
    text = f"{type(exc).__name__}: {exc}"
    return text.replace("\n", " ")[:400]


def is_rejection(exc: BaseException) -> bool:
    return isinstance(exc, (MessageRejectedByBrokerError, PubSubPlusClientError))


def disconnect(services: Iterable[MessagingService]) -> None:
    for service in services:
        try:
            service.disconnect()
        except Exception:
            pass
