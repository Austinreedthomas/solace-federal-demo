"""Synthetic topics and the expected routing matrix.

Object id 25544 is a synthetic label, the same one on the slides.
Nothing here is a spacecraft transmission or a real launch detection.
The primary alert text is exactly "Launch detected".
A status heartbeat is a different event category so the launch subscription can miss it.
"""

from __future__ import annotations

ALLOWED_EXCEPTION = "ssa/unclass/>"
DENIED_TOPIC = "admin/test/probe"
DENIED_SUBSCRIPTION = "admin/test/>"

LAUNCH_ALERT_TEXT = "Launch detected"
LAUNCH_SUBSCRIPTION = "ssa/unclass/*/launch/>"
OBJECT_SUBSCRIPTION = "ssa/unclass/ground1/*/25544/>"

TOPIC_BOTH = "ssa/unclass/ground1/launch/25544/alert"
TOPIC_OTHER_SITE = "ssa/unclass/ground2/launch/25544/alert"
TOPIC_OBJECT_ONLY = "ssa/unclass/ground1/status/25544/heartbeat"
TOPIC_HEARTBEAT_GROUND2 = "ssa/unclass/ground2/status/25544/heartbeat"
TOPIC_DIRECT_ONLY = "ssa/unclass/ground1/live/25544/update"
TOPIC_DIRECT_GROUND2 = "ssa/unclass/ground2/live/25544/update"
# Optional weather example. Not object 25544, and not a launch, so the
# existing launch and object subscriptions do not match it.
WEATHER_TOPIC = "ssa/unclass/ground1/weather/station-1/reading"
WEATHER_SUBSCRIPTION = "ssa/unclass/ground1/weather/>"
WEATHER_TOPICS = {
    "ground1": WEATHER_TOPIC,
    "ground2": "ssa/unclass/ground2/weather/station-1/reading",
}

QUEUE_NAME = "q-ssa-operator"
# The browser console binds this queue, not q-ssa-operator, so it does not
# acknowledge messages the terminal quickstart left on the core queue.
WEB_QUEUE_NAME = "q-ssa-web-console"
QUEUE_SUBSCRIPTION = "ssa/unclass/ground1/launch/>"

PUBLISHER_PROFILE = "ssa-publisher-acl"
SUBSCRIBER_PROFILE = "ssa-subscriber-acl"
PUBLISHER_CLIENT_PROFILE = "ssa-publisher-client"
SUBSCRIBER_CLIENT_PROFILE = "ssa-subscriber-client"

CONSUMER_LAUNCH = "launch-any-site"
CONSUMER_OBJECT = "one-object-ground1-25544"
CONSUMER_WEATHER = "weather-ground1"

# Stable ids. Reruns publish the same ids after the demo queue is recreated.
ROUTING_CASES = (
    {
        "alert_id": "routing-both-001",
        "topic": TOPIC_BOTH,
        "expect": {CONSUMER_LAUNCH: True, CONSUMER_OBJECT: True},
    },
    {
        "alert_id": "routing-other-site-001",
        "topic": TOPIC_OTHER_SITE,
        "expect": {CONSUMER_LAUNCH: True, CONSUMER_OBJECT: False},
    },
    {
        "alert_id": "routing-object-only-001",
        "topic": TOPIC_OBJECT_ONLY,
        "expect": {CONSUMER_LAUNCH: False, CONSUMER_OBJECT: True},
    },
)

ACCESS_ALLOWED_ID = "access-allowed-001"
ACCESS_DENIED_ID = "access-denied-001"
DELIVERY_DIRECT_ID = "delivery-direct-001"
DELIVERY_GUARANTEED_ID = "delivery-guaranteed-001"


def alert_body(alert_id: str, topic: str) -> dict:
    parts = topic.split("/")
    # ssa / unclass / site / kind / object / leaf
    site = parts[2] if len(parts) > 2 else ""
    kind = parts[3] if len(parts) > 3 else ""
    object_id = parts[4] if len(parts) > 4 else ""
    if kind == "launch":
        alert_text = LAUNCH_ALERT_TEXT
    elif kind == "status":
        alert_text = "Heartbeat sample"
    elif kind == "live":
        alert_text = "Live update sample"
    elif kind == "weather":
        alert_text = "Weather reading"
    else:
        alert_text = "Synthetic sample"
    return {
        "alertId": alert_id,
        "alertText": alert_text,
        "topic": topic,
        "site": site,
        "kind": kind,
        "objectId": object_id,
        "classificationLabel": "unclass",
        "synthetic": True,
        "note": "Synthetic unclassified sample. Not a spacecraft transmission or a launch detection.",
    }
