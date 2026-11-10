"""Three presenter steps. Each one talks to the broker and returns expected versus observed."""

from __future__ import annotations

from dataclasses import dataclass, field

from solace_demo.catalog import (
    ACCESS_ALLOWED_ID,
    ACCESS_DENIED_ID,
    CONSUMER_LAUNCH,
    CONSUMER_OBJECT,
    DELIVERY_DIRECT_ID,
    DELIVERY_GUARANTEED_ID,
    DENIED_SUBSCRIPTION,
    DENIED_TOPIC,
    LAUNCH_SUBSCRIPTION,
    OBJECT_SUBSCRIPTION,
    QUEUE_NAME,
    ROUTING_CASES,
    TOPIC_BOTH,
    TOPIC_DIRECT_ONLY,
    alert_body,
)
from solace_demo.config import LabConfig
from solace_demo.messaging import (
    collect_direct,
    connect,
    disconnect,
    is_rejection,
    publish_direct,
    publish_persistent,
    receive_guaranteed,
    safe_error,
    try_subscribe,
)
from solace_demo.provision import monitor_live_clients, recreate_queue
from solace_demo.semp import Semp


@dataclass
class Report:
    name: str
    passed: bool
    lines: list[str] = field(default_factory=list)

    def add(self, text: str) -> None:
        self.lines.append(text)


ARCHITECTURE_BOUNDARIES = [
    "Not in this lab: Solace Cloud, a static bridge, DMR, a second broker, or Kafka.",
    "Separate from this lab, and not retested here: direct cloud-to-laptop via a locally initiated static bridge, remote subscription ssa/>.",
    "Not proven: DMR mesh, bidirectional flow, bridge or network outage recovery, ACL tests on that cloud path, Kafka bridging.",
]


def architecture_lines(host: str, vpn: str) -> list[str]:
    shown = host[len("tcp://") :] if host.startswith("tcp://") else host
    return [
        f"Lab broker: one local Solace Standard software broker, Message VPN {vpn}, SMF on {shown}.",
        *ARCHITECTURE_BOUNDARIES,
    ]


def _publisher(config: LabConfig):
    return connect(config, config.publisher_username, config.publisher_password)


def _subscriber(config: LabConfig):
    return connect(config, config.subscriber_username, config.subscriber_password)


def run_routing(config: LabConfig) -> Report:
    report = Report("1 routing", True)
    report.add("Two direct consumers, one publisher. Topics are not pre-created.")
    report.add(f"{CONSUMER_LAUNCH} subscribes {LAUNCH_SUBSCRIPTION}")
    report.add(f"{CONSUMER_OBJECT} subscribes {OBJECT_SUBSCRIPTION}")
    opened = []
    try:
        publisher = _publisher(config)
        launch_consumer = _subscriber(config)
        one_object = _subscriber(config)
        opened.extend((publisher, launch_consumer, one_object))
        # Prime the subscriptions before the bounded publish burst.
        # collect_direct both subscribes and drains, so publish first into live receivers.
        from solace.messaging.resources.topic_subscription import TopicSubscription

        receivers = {
            CONSUMER_LAUNCH: launch_consumer.create_direct_message_receiver_builder()
            .with_subscriptions([TopicSubscription.of(LAUNCH_SUBSCRIPTION)])
            .build(),
            CONSUMER_OBJECT: one_object.create_direct_message_receiver_builder()
            .with_subscriptions([TopicSubscription.of(OBJECT_SUBSCRIPTION)])
            .build(),
        }
        for receiver in receivers.values():
            receiver.start()
        try:
            for case in ROUTING_CASES:
                body = alert_body(case["alert_id"], case["topic"])
                publish_direct(publisher, case["topic"], case["alert_id"], body)
                report.add(
                    f"PUBLISH {case['alert_id']} topic={case['topic']} alertText={body['alertText']}"
                )
            import time

            time.sleep(0.5)
            got = {name: [] for name in receivers}
            for name, receiver in receivers.items():
                while True:
                    message = receiver.receive_message(timeout=300)
                    if message is None:
                        break
                    from solace_demo.messaging import read_alert_id

                    got[name].append(read_alert_id(message))
        finally:
            for receiver in receivers.values():
                receiver.terminate()
        for case in ROUTING_CASES:
            for consumer, expect in case["expect"].items():
                seen = case["alert_id"] in got[consumer]
                ok = seen is expect
                report.passed = report.passed and ok
                mark = "RECEIVE" if seen else "MISS"
                report.add(
                    f"{mark} {consumer} id={case['alert_id']} expected={'receive' if expect else 'miss'} observed={'receive' if seen else 'miss'} {'OK' if ok else 'DIFF'}"
                )
    finally:
        disconnect(opened)
    return report


def run_access(config: LabConfig) -> Report:
    report = Report("2 access", True)
    report.add("Publisher ACL: publish default disallow, allow exception ssa/unclass/>, subscribe default disallow.")
    report.add("Subscriber ACL: subscribe default disallow, allow exception ssa/unclass/>, publish default disallow.")
    report.add("admin/test/> is denied because it matches no allow exception, not because of an unnamed built-in profile.")
    report.add("Queue bind permission is separate and is not what this step checks.")
    opened = []
    try:
        publisher = _publisher(config)
        subscriber = _subscriber(config)
        opened.extend((publisher, subscriber))
        allowed_sub = try_subscribe(subscriber, LAUNCH_SUBSCRIPTION)
        report.add(f"SUBSCRIBE {LAUNCH_SUBSCRIPTION} observed={allowed_sub}")
        if allowed_sub != "accepted":
            report.passed = False
        # Receive the allowed publish on a fresh subscription.
        from solace.messaging.resources.topic_subscription import TopicSubscription

        receiver = (
            subscriber.create_direct_message_receiver_builder()
            .with_subscriptions([TopicSubscription.of(LAUNCH_SUBSCRIPTION)])
            .build()
        )
        receiver.start()
        try:
            allowed_body = alert_body(ACCESS_ALLOWED_ID, TOPIC_BOTH)
            publish_direct(publisher, TOPIC_BOTH, ACCESS_ALLOWED_ID, allowed_body)
            report.add(f"PUBLISH allowed alertText={allowed_body['alertText']}")
            from solace_demo.messaging import read_alert_id

            message = receiver.receive_message(timeout=3000)
            got = read_alert_id(message) if message is not None else ""
        finally:
            receiver.terminate()
        allowed_ok = got == ACCESS_ALLOWED_ID
        report.passed = report.passed and allowed_ok
        report.add(
            f"ALLOWED RECEIVE id={ACCESS_ALLOWED_ID} observed={got or 'none'} {'OK' if allowed_ok else 'DIFF'}"
        )
        try:
            result = publish_persistent(
                publisher,
                DENIED_TOPIC,
                ACCESS_DENIED_ID,
                alert_body(ACCESS_DENIED_ID, DENIED_TOPIC),
            )
            report.add(f"DENIED PUBLISH {DENIED_TOPIC} observed={result} DIFF")
            report.passed = False
        except Exception as exc:
            denied_ok = is_rejection(exc)
            report.passed = report.passed and denied_ok
            report.add(
                f"DENIED PUBLISH {DENIED_TOPIC} observed={safe_error(exc)} {'OK' if denied_ok else 'DIFF'}"
            )
        try:
            denied_sub = try_subscribe(subscriber, DENIED_SUBSCRIPTION)
            report.add(f"DENIED SUBSCRIBE {DENIED_SUBSCRIPTION} observed={denied_sub} DIFF")
            report.passed = False
        except Exception as exc:
            denied_sub_ok = is_rejection(exc)
            report.passed = report.passed and denied_sub_ok
            report.add(
                f"DENIED SUBSCRIBE {DENIED_SUBSCRIPTION} observed={safe_error(exc)} {'OK' if denied_sub_ok else 'DIFF'}"
            )
        for username in (config.publisher_username, config.subscriber_username):
            for line in monitor_live_clients(config, username):
                report.add(line)
        report.add(
            "Subscribe ACL denial is the client subcode SUBSCRIPTION_ACL_DENIED. "
            "The connected-client monitor object has publishTopicAclRxDiscardedMsgCount and no separate subscribe-ACL counter."
        )
    finally:
        disconnect(opened)
    return report


def run_delivery(config: LabConfig) -> Report:
    report = Report("3 delivery", True)
    report.add("Offline consumer, publisher still connected to this same local broker.")
    report.add("This is not a bridge or network outage. That case needs a cloud-side bridge queue and guaranteed bridging, which are not configured here and are not proven.")
    report.add(f"Direct topic {TOPIC_DIRECT_ONLY} matches no queue, so a later subscriber cannot recover it.")
    report.add(f"Guaranteed Launch detected alert on {TOPIC_BOTH} is spooled on {QUEUE_NAME} until the owner binds.")
    recreate_queue(Semp(config), config)
    opened = []
    try:
        publisher = _publisher(config)
        opened.append(publisher)
        publish_direct(
            publisher,
            TOPIC_DIRECT_ONLY,
            DELIVERY_DIRECT_ID,
            alert_body(DELIVERY_DIRECT_ID, TOPIC_DIRECT_ONLY),
        )
        report.add(f"PUBLISH direct id={DELIVERY_DIRECT_ID} while no direct subscriber is connected")
        guaranteed_body = alert_body(DELIVERY_GUARANTEED_ID, TOPIC_BOTH)
        acked = publish_persistent(publisher, TOPIC_BOTH, DELIVERY_GUARANTEED_ID, guaranteed_body)
        report.add(
            f"PUBLISH guaranteed id={DELIVERY_GUARANTEED_ID} topic={TOPIC_BOTH} "
            f"alertText={guaranteed_body['alertText']} broker={acked} while the queue consumer is offline"
        )
        subscriber = _subscriber(config)
        opened.append(subscriber)
        missed = collect_direct(subscriber, TOPIC_DIRECT_ONLY, 1500)
        direct_ok = DELIVERY_DIRECT_ID not in missed and not missed
        report.passed = report.passed and direct_ok
        report.add(
            f"OBSERVE direct after reconnect ids={missed or ['none']} expected=miss {'OK' if direct_ok else 'DIFF'}"
        )
        held = receive_guaranteed(subscriber, 3000)
        guaranteed_ok = held == [DELIVERY_GUARANTEED_ID]
        report.passed = report.passed and guaranteed_ok
        report.add(
            f"OBSERVE guaranteed after bind ids={held or ['none']} expected={[DELIVERY_GUARANTEED_ID]} {'OK' if guaranteed_ok else 'DIFF'}"
        )
    finally:
        disconnect(opened)
    return report
