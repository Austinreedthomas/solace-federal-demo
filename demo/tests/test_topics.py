from solace_demo.catalog import (
    ALLOWED_EXCEPTION,
    CONSUMER_LAUNCH,
    CONSUMER_OBJECT,
    DENIED_TOPIC,
    LAUNCH_ALERT_TEXT,
    LAUNCH_SUBSCRIPTION,
    OBJECT_SUBSCRIPTION,
    QUEUE_SUBSCRIPTION,
    ROUTING_CASES,
    TOPIC_BOTH,
    TOPIC_DIRECT_GROUND2,
    TOPIC_DIRECT_ONLY,
    TOPIC_HEARTBEAT_GROUND2,
    TOPIC_OBJECT_ONLY,
    TOPIC_OTHER_SITE,
    alert_body,
)
from solace_demo.config import ConfigError
from solace_demo.topics import TopicSyntaxError, acl_decision, subscription_matches

import pytest


def test_routing_matrix_matches_subscription_rules():
    subs = {
        CONSUMER_LAUNCH: LAUNCH_SUBSCRIPTION,
        CONSUMER_OBJECT: OBJECT_SUBSCRIPTION,
    }
    for case in ROUTING_CASES:
        for consumer, expect in case["expect"].items():
            assert subscription_matches(subs[consumer], case["topic"]) is expect


def test_launch_text_is_exact_and_the_other_category_is_not():
    launch = alert_body("routing-both-001", TOPIC_BOTH)
    other = alert_body("routing-object-only-001", TOPIC_OBJECT_ONLY)
    direct = alert_body("delivery-direct-001", TOPIC_DIRECT_ONLY)
    assert launch["kind"] == "launch"
    assert launch["alertText"] == LAUNCH_ALERT_TEXT == "Launch detected"
    assert other["kind"] == "status"
    assert other["alertText"] != "Launch detected"
    assert direct["alertText"] != "Launch detected"
    assert launch["synthetic"] is True
    assert "detection" in launch["note"]


def test_greater_than_needs_one_level_and_must_be_last():
    assert subscription_matches("ssa/>", TOPIC_BOTH)
    assert not subscription_matches("ssa/>", "ssa")
    with pytest.raises(TopicSyntaxError):
        subscription_matches("ssa/>/extra", "ssa/unclass/alert")


def test_star_is_one_level_and_launch_does_not_match_status():
    assert subscription_matches(LAUNCH_SUBSCRIPTION, "ssa/unclass/ground2/launch/25544/alert")
    assert not subscription_matches(LAUNCH_SUBSCRIPTION, TOPIC_OBJECT_ONLY)


def test_direct_topic_does_not_match_the_guaranteed_queue_subscription():
    assert not subscription_matches(QUEUE_SUBSCRIPTION, TOPIC_DIRECT_ONLY)
    assert subscription_matches(QUEUE_SUBSCRIPTION, TOPIC_BOTH)


def test_configured_acl_matrix_is_not_an_implicit_broker_default():
    publish_default = "disallow"
    publish_exceptions = (ALLOWED_EXCEPTION,)
    assert acl_decision(TOPIC_BOTH, publish_default, publish_exceptions) == "allow"
    assert acl_decision(DENIED_TOPIC, publish_default, publish_exceptions) == "disallow"
    assert acl_decision(TOPIC_DIRECT_ONLY, publish_default, publish_exceptions) == "allow"
    # No exception: default disallow stays disallow. This is the profile we create.
    assert acl_decision(TOPIC_BOTH, "disallow", ()) == "disallow"


def test_guaranteed_prefix_stays_off_the_direct_bridge_subscription():
    from solace_demo.live import plan_send
    from solace_demo.topics import DIRECT_BRIDGE_SUBSCRIPTION, guaranteed_topic, validate_guaranteed_prefix

    prefix = "ssa-guaranteed/unclass"
    assert validate_guaranteed_prefix(prefix) == prefix
    for topic in (TOPIC_BOTH, TOPIC_OTHER_SITE, TOPIC_OBJECT_ONLY, TOPIC_DIRECT_ONLY, TOPIC_DIRECT_GROUND2):
        assert subscription_matches(DIRECT_BRIDGE_SUBSCRIPTION, topic)
        isolated = guaranteed_topic(topic, prefix)
        assert not subscription_matches(DIRECT_BRIDGE_SUBSCRIPTION, isolated)
        assert not subscription_matches(LAUNCH_SUBSCRIPTION, isolated)
        assert not subscription_matches(OBJECT_SUBSCRIPTION, isolated)
        assert not subscription_matches(QUEUE_SUBSCRIPTION, isolated)
        assert subscription_matches(prefix + "/>", isolated)
    for bad in ("ssa/unclass", "ssa/other", "ssa-guaranteed", "ssa-guaranteed/unclass/>", "ssa-guaranteed/unclass/", "ssa-guaranteed/unclass/extra", ""):
        with pytest.raises(ConfigError) as raised:
            validate_guaranteed_prefix(bad)
        if bad:
            assert bad not in str(raised.value)
    for bad in (
        "ssa-guaranteed\nunclass",
        "ssa-guaranteed\r/unclass",
        "ssa-guaranteed\x00/unclass",
        "ssa-\x01guaranteed/unclass",
        "ssa-guaranteed\x7f/unclass",
        "ssa-guaranteed/\u00a0unclass",
    ):
        with pytest.raises(ConfigError) as raised:
            validate_guaranteed_prefix(bad)
        text = str(raised.value)
        assert bad not in text
        assert all(ch not in text for ch in bad if ch.isspace() or ord(ch) < 32 or ord(ch) == 127)
    assert plan_send("launch-ground1", prefix, True)["topic"] == TOPIC_BOTH
    assert plan_send("guaranteed-launch", "", False)["topic"] == TOPIC_BOTH
    assert plan_send("guaranteed-launch", "", True)["blocked"] is True
    isolated = plan_send("guaranteed-launch", prefix, True)
    assert isolated["topic"] == "ssa-guaranteed/unclass/ground1/launch/25544/alert"
    body = alert_body("ex-1", isolated["topic"])
    assert body["site"] == "ground1"
    assert body["kind"] == "launch"
    assert body["objectId"] == "25544"


def test_heartbeat_follows_the_selected_ground():
    from pathlib import Path

    from solace_demo.live import plan_send

    ground1 = plan_send("heartbeat-ground1", "", False)
    ground2 = plan_send("heartbeat-ground2", "", False)
    plain = plan_send("heartbeat", "", True)
    assert ground1["topic"] == TOPIC_OBJECT_ONLY == "ssa/unclass/ground1/status/25544/heartbeat"
    assert ground1["delivery"] == "direct"
    assert ground1["blocked"] is False
    assert ground2["topic"] == TOPIC_HEARTBEAT_GROUND2 == "ssa/unclass/ground2/status/25544/heartbeat"
    assert ground2["delivery"] == "direct"
    assert plain["topic"] == TOPIC_OBJECT_ONLY
    assert plan_send("heartbeat-ground2", "ssa-guaranteed/unclass", True)["topic"] == TOPIC_HEARTBEAT_GROUND2
    body = alert_body("hb-2", ground2["topic"])
    assert body["site"] == "ground2"
    assert body["kind"] == "status"
    assert body["alertText"] == "Heartbeat sample"
    assert subscription_matches(OBJECT_SUBSCRIPTION, TOPIC_OBJECT_ONLY)
    assert not subscription_matches(OBJECT_SUBSCRIPTION, TOPIC_HEARTBEAT_GROUND2)
    assert not subscription_matches(LAUNCH_SUBSCRIPTION, TOPIC_HEARTBEAT_GROUND2)
    assert not subscription_matches(QUEUE_SUBSCRIPTION, TOPIC_HEARTBEAT_GROUND2)
    assert not subscription_matches(LAUNCH_SUBSCRIPTION, TOPIC_OBJECT_ONLY)
    page = (Path(__file__).resolve().parent.parent / "web" / "publisher.html").read_text(encoding="utf-8")
    operator = (Path(__file__).resolve().parent.parent / "web" / "operator.html").read_text(encoding="utf-8")
    assert "function heartbeatKind()" in page
    assert 'send(heartbeatKind()' in page
    assert 'send("heartbeat"' not in page
    assert 'return "heartbeat-" + selectedGround()' in page
    assert 'return "guaranteed-launch-" + selectedGround()' in page
    assert 'return "direct-live-" + selectedGround()' in page
    assert "selected ground" in page
    assert "including the ground 1 heartbeat and the queued launch alert for this object" in operator
    assert "every launch alert" in operator
    assert "<h2>Broker queue</h2>" not in operator
    assert 'id="broker-queue"' not in operator
    assert 'ground1Object(event.topic) ? "one-object-ground1-25544"' in operator
    assert "function guaranteedKind()" in page
    assert "function directKind()" in page
    assert "send(guaranteedKind()" in page
    assert "send(directKind()" in page
    assert 'send("guaranteed-launch"' not in page
    assert 'send("direct-live"' not in page
    assert 'tag.textContent = deliveryTag(event)' in operator
    assert "Already on this console's queue" in operator
    guaranteed = plan_send("guaranteed-launch", "ssa-guaranteed/unclass", True)
    guaranteed_body = alert_body("g-1", guaranteed["topic"])
    assert guaranteed_body["site"] == "ground1"
    assert guaranteed_body["objectId"] == "25544"
    assert guaranteed_body["kind"] == "launch"
    prefix = "ssa-guaranteed/unclass"
    assert plan_send("direct-live", "", False)["topic"] == TOPIC_DIRECT_ONLY
    assert plan_send("direct-live-ground1", "", False)["topic"] == TOPIC_DIRECT_ONLY
    assert plan_send("direct-live-ground2", "", False)["topic"] == TOPIC_DIRECT_GROUND2 == "ssa/unclass/ground2/live/25544/update"
    assert plan_send("direct-live-ground2", prefix, True)["topic"] == TOPIC_DIRECT_GROUND2
    assert not subscription_matches(OBJECT_SUBSCRIPTION, TOPIC_DIRECT_GROUND2)
    assert not subscription_matches(LAUNCH_SUBSCRIPTION, TOPIC_DIRECT_GROUND2)
    assert plan_send("guaranteed-launch-ground1", prefix, True)["topic"] == f"{prefix}/ground1/launch/25544/alert"
    assert plan_send("guaranteed-launch", prefix, True)["topic"] == f"{prefix}/ground1/launch/25544/alert"
    ground2_guaranteed = plan_send("guaranteed-launch-ground2", prefix, True)
    assert ground2_guaranteed["topic"] == f"{prefix}/ground2/launch/25544/alert"
    assert ground2_guaranteed["delivery"] == "guaranteed"
    assert ground2_guaranteed["blocked"] is False
    assert plan_send("guaranteed-launch-ground2", "", True)["blocked"] is True
    assert plan_send("guaranteed-launch-ground2", "", False)["topic"] == TOPIC_OTHER_SITE
    from solace_demo.live import display_feed

    ground1_queued = {
        "feed": "broker-queue",
        "delivery": "queued",
        "topic": f"{prefix}/ground1/launch/25544/alert",
    }
    ground2_queued = {
        "feed": "broker-queue",
        "delivery": "queued",
        "topic": ground2_guaranteed["topic"],
    }
    assert display_feed(ground1_queued) == "one-object-ground1-25544"
    assert display_feed(ground2_queued) == ""
    assert display_feed({"feed": "launch-any-site", "delivery": "direct", "topic": TOPIC_OTHER_SITE}) == "launch-any-site"


def test_weather_topic_is_direct_and_not_object_25544():
    from solace_demo.catalog import WEATHER_SUBSCRIPTION, WEATHER_TOPIC
    from solace_demo.topics import DIRECT_BRIDGE_SUBSCRIPTION

    assert "25544" not in WEATHER_TOPIC
    assert subscription_matches(WEATHER_SUBSCRIPTION, WEATHER_TOPIC)
    assert subscription_matches(DIRECT_BRIDGE_SUBSCRIPTION, WEATHER_TOPIC)
    assert not subscription_matches(LAUNCH_SUBSCRIPTION, WEATHER_TOPIC)
    assert not subscription_matches(OBJECT_SUBSCRIPTION, WEATHER_TOPIC)
    assert not subscription_matches(QUEUE_SUBSCRIPTION, WEATHER_TOPIC)
    assert not subscription_matches("ssa-guaranteed/unclass/>", WEATHER_TOPIC)
    body = alert_body("wx-1", WEATHER_TOPIC)
    assert body["alertText"] == "Weather reading"
    assert body["objectId"] == "station-1"
