"""Unit tests for Operations Watch incident correlation. No broker required."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "agent_mesh" / "sam_bonus" / "src"
sys.path.insert(0, str(SRC))

from ops_watch.report import (  # noqa: E402
    build_incident_report,
    latest_window,
    subscription_matches,
    topic_fields,
)


SUBS = ["ssa/unclass/ground1/launch/>", "guaranteed/ground1/launch/>"]


def _iso(ts: datetime) -> str:
    return ts.isoformat(timespec="seconds")


def test_subscription_matches_ground1_launch_only():
    assert subscription_matches("ssa/unclass/ground1/launch/>", "ssa/unclass/ground1/launch/25544/alert")
    assert not subscription_matches("ssa/unclass/ground1/launch/>", "ssa/unclass/ground2/launch/25544/alert")
    assert not subscription_matches("ssa/unclass/ground1/launch/>", "ssa/unclass/ground1/status/25544/heartbeat")
    assert subscription_matches("guaranteed/ground1/launch/>", "guaranteed/ground1/launch/25544/alert")


def test_topic_fields_reads_site_kind_object():
    fields = topic_fields("ssa/unclass/ground1/launch/25544/alert")
    assert fields == {"site": "ground1", "kind": "launch", "objectId": "25544"}
    fields = topic_fields("acme-guaranteed/ground2/status/25544/heartbeat")
    assert fields["site"] == "ground2"
    assert fields["kind"] == "status"
    fields = topic_fields(
        "mesh/guaranteed/ground1/launch/25544/alert",
        prefix="mesh/guaranteed",
    )
    assert fields == {"site": "ground1", "kind": "launch", "objectId": "25544"}


def test_latest_window_completed_and_open():
    t0 = datetime(2026, 11, 10, 8, 0, tzinfo=datetime.now().astimezone().tzinfo)
    records = [
        {"type": "operator_event", "kind": "disconnected", "at": _iso(t0)},
        {"type": "operator_event", "kind": "reconnected", "at": _iso(t0 + timedelta(seconds=45))},
    ]
    window = latest_window(records)
    assert window is not None
    assert window["open"] is False
    assert window["disconnectedAt"] == _iso(t0)
    assert window["reconnectedAt"] == _iso(t0 + timedelta(seconds=45))

    open_records = records[:1]
    open_window = latest_window(open_records)
    assert open_window is not None and open_window["open"] is True
    assert open_window["reconnectedAt"] is None


def test_incident_report_correlates_queued_vs_published():
    t0 = datetime(2026, 11, 10, 8, 0, tzinfo=datetime.now().astimezone().tzinfo)
    t1 = t0 + timedelta(seconds=10)
    t2 = t0 + timedelta(seconds=20)
    t3 = t0 + timedelta(seconds=30)
    t4 = t0 + timedelta(seconds=50)
    records = [
        {"type": "queue_subscriptions", "at": _iso(t0), "subscriptions": SUBS},
        {"type": "operator_event", "kind": "disconnected", "at": _iso(t0), "bindCount": 0, "queueDepth": 0},
        {
            "type": "alert",
            "at": _iso(t1),
            "alertId": "g1-launch-1",
            "topic": "guaranteed/ground1/launch/25544/alert",
            "site": "ground1",
            "kind": "launch",
            "objectId": "25544",
        },
        {
            "type": "alert",
            "at": _iso(t2),
            "alertId": "g1-hb-1",
            "topic": "ssa/unclass/ground1/status/25544/heartbeat",
            "site": "ground1",
            "kind": "status",
            "objectId": "25544",
        },
        {
            "type": "alert",
            "at": _iso(t3),
            "alertId": "g2-launch-1",
            "topic": "guaranteed/ground2/launch/25544/alert",
            "site": "ground2",
            "kind": "launch",
            "objectId": "25544",
        },
        {
            "type": "queue_snapshot",
            "at": _iso(t3),
            "queueDepth": 1,
            "bindCount": 0,
            "messages": [{"applicationMessageId": "g1-launch-1", "topic": "guaranteed/ground1/launch/25544/alert"}],
        },
        {"type": "operator_event", "kind": "reconnected", "at": _iso(t4), "bindCount": 1, "queueDepth": 0},
        {"type": "queue_snapshot", "at": _iso(t4), "queueDepth": 0, "bindCount": 1, "messages": []},
    ]
    report = build_incident_report(
        records,
        current_stats={"spooledMsgCount": 0, "bindCount": 1, "connected": True, "queueName": "queue-local-operator-guaranteed"},
        subscriptions=SUBS,
        queue_name="queue-local-operator-guaranteed",
        now=t4,
    )
    assert report["incidentRecorded"] is True
    assert report["queuedAlertIds"] == ["g1-launch-1"]
    assert report["queuedEventCount"] == 1
    assert report["publishedEventCount"] == 3
    not_queued_ids = {e["alertId"] for e in report["notQueuedEvents"]}
    assert not_queued_ids == {"g1-hb-1", "g2-launch-1"}
    assert report["peakQueueDepth"] == 1
    assert report["queueDepth"] == 0
    assert report["countsMatch"] is True
    assert report["queueEmpty"] is True
    assert report["allQueuedMessagesDelivered"] is True
    assert report["disconnectWindow"]["durationSeconds"] == 50
    assert report["operatorConnected"] is True


def test_incident_report_open_window_is_not_delivered():
    t0 = datetime(2026, 11, 10, 8, 0, tzinfo=datetime.now().astimezone().tzinfo)
    records = [
        {"type": "operator_event", "kind": "disconnected", "at": _iso(t0), "bindCount": 0, "queueDepth": 0},
        {
            "type": "alert",
            "at": _iso(t0 + timedelta(seconds=5)),
            "alertId": "g1-launch-2",
            "topic": "ssa/unclass/ground1/launch/25544/alert",
            "site": "ground1",
            "kind": "launch",
            "objectId": "25544",
        },
        {"type": "queue_snapshot", "at": _iso(t0 + timedelta(seconds=5)), "queueDepth": 1, "messages": []},
    ]
    report = build_incident_report(
        records,
        current_stats={"spooledMsgCount": 1, "bindCount": 0, "connected": False},
        subscriptions=["ssa/unclass/ground1/launch/>"],
        queue_name="q-ssa-web-console",
        now=t0 + timedelta(seconds=20),
    )
    assert report["incidentRecorded"] is True
    assert report["disconnectWindow"]["open"] is True
    assert report["queuedAlertIds"] == ["g1-launch-2"]
    assert report["allQueuedMessagesDelivered"] is False
    assert report["queueEmpty"] is False


def test_incident_report_without_window():
    report = build_incident_report(
        [],
        current_stats={"spooledMsgCount": 0, "bindCount": 1, "connected": True, "queueName": "q"},
        queue_name="q",
    )
    assert report["incidentRecorded"] is False
    assert report["operatorConnected"] is True
    assert report["queueDepth"] == 0


def test_three_matching_launches_counts_match():
    t0 = datetime(2026, 11, 10, 9, 0, tzinfo=datetime.now().astimezone().tzinfo)
    records = [{"type": "operator_event", "kind": "disconnected", "at": _iso(t0), "bindCount": 0, "queueDepth": 0}]
    for i in range(3):
        ts = t0 + timedelta(seconds=5 * (i + 1))
        records.append(
            {
                "type": "alert",
                "at": _iso(ts),
                "alertId": f"launch-{i+1}",
                "topic": "ssa/unclass/ground1/launch/25544/alert",
                "site": "ground1",
                "kind": "launch",
                "objectId": "25544",
            }
        )
        records.append({"type": "queue_snapshot", "at": _iso(ts), "queueDepth": i + 1, "messages": []})
    reconnect = t0 + timedelta(seconds=40)
    records.append({"type": "operator_event", "kind": "reconnected", "at": _iso(reconnect), "bindCount": 1, "queueDepth": 0})
    report = build_incident_report(
        records,
        current_stats={"spooledMsgCount": 0, "bindCount": 1, "connected": True},
        subscriptions=["ssa/unclass/ground1/launch/>"],
        queue_name="q",
        now=reconnect,
    )
    assert report["queuedAlertIds"] == ["launch-1", "launch-2", "launch-3"]
    assert report["peakQueueDepth"] == 3
    assert report["countsMatch"] is True
    assert report["allQueuedMessagesDelivered"] is True
