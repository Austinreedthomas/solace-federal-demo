"""Correlate a primary-operator disconnect window with queued alerts.

Pure functions. No broker I/O, no secrets.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def subscription_matches(subscription: str, topic: str) -> bool:
    """Solace-style match: '*' is one level, '>' is one or more at the end."""
    if not subscription or not topic:
        return False
    sub = subscription.split("/")
    top = topic.split("/")
    return _match(sub, top)


def _match(sub: list[str], topic: list[str]) -> bool:
    if not sub:
        return not topic
    token = sub[0]
    if token == ">":
        return len(sub) == 1 and len(topic) >= 1
    if not topic:
        return False
    if token != "*" and token != topic[0]:
        return False
    return _match(sub[1:], topic[1:])


def topic_fields(topic: str, prefix: str | None = None) -> dict:
    """Return site, kind, and objectId from a demo topic.

    Direct topics use the ssa/unclass root. Guaranteed topics replace that
    root with SOLACE_GUARANTEED_TOPIC_PREFIX, which may be one or more levels.
    """
    parts = [p for p in (topic or "").split("/") if p]
    if prefix:
        pre = [p for p in prefix.strip("/").split("/") if p]
        if pre and parts[: len(pre)] == pre:
            rest = parts[len(pre) :]
            return {
                "site": rest[0] if rest else "",
                "kind": rest[1] if len(rest) > 1 else "",
                "objectId": rest[2] if len(rest) > 2 else "",
            }
    if len(parts) >= 3 and parts[0] == "ssa" and parts[1] == "unclass":
        return {
            "site": parts[2],
            "kind": parts[3] if len(parts) > 3 else "",
            "objectId": parts[4] if len(parts) > 4 else "",
        }
    for i, token in enumerate(parts):
        if token.startswith("ground"):
            return {
                "site": token,
                "kind": parts[i + 1] if i + 1 < len(parts) else "",
                "objectId": parts[i + 2] if i + 2 < len(parts) else "",
            }
    return {
        "site": parts[2] if len(parts) > 2 else "",
        "kind": parts[3] if len(parts) > 3 else "",
        "objectId": parts[4] if len(parts) > 4 else "",
    }


def topic_matches_any(topic: str, subscriptions: Sequence[str]) -> bool:
    return any(subscription_matches(sub, topic) for sub in subscriptions if sub)


def _in_window(ts: str | None, start: str | None, end: str | None) -> bool:
    t = parse_iso(ts)
    t0 = parse_iso(start)
    t1 = parse_iso(end)
    if t is None:
        return False
    if t0 is not None and t < t0:
        return False
    if t1 is not None and t > t1:
        return False
    return True


def latest_window(records: Sequence[dict], *, now: Optional[datetime] = None, lookback: Optional[timedelta] = None) -> Optional[dict]:
    """Return the most recent disconnect window.

    A completed window has disconnectedAt and reconnectedAt. An open window
    has disconnectedAt only (operator still down).
    """
    events = [r for r in records if r.get("type") == "operator_event"]
    windows: List[dict] = []
    open_disc: Optional[dict] = None
    for rec in events:
        kind = rec.get("kind")
        if kind == "disconnected":
            open_disc = {
                "disconnectedAt": rec.get("at"),
                "reconnectedAt": None,
                "open": True,
                "disconnectBindCount": rec.get("bindCount"),
                "disconnectQueueDepth": rec.get("queueDepth"),
            }
        elif kind == "reconnected" and open_disc is not None:
            open_disc["reconnectedAt"] = rec.get("at")
            open_disc["open"] = False
            open_disc["reconnectBindCount"] = rec.get("bindCount")
            open_disc["reconnectQueueDepth"] = rec.get("queueDepth")
            windows.append(open_disc)
            open_disc = None
    if open_disc is not None:
        windows.append(open_disc)
    if not windows:
        return None
    if lookback is not None:
        cutoff = (now or datetime.now().astimezone()) - lookback
        windows = [
            w
            for w in windows
            if (parse_iso(w.get("disconnectedAt")) or cutoff) >= cutoff
        ]
        if not windows:
            return None
    return windows[-1]


def _alert_summary(rec: dict) -> dict:
    topic = rec.get("topic") or ""
    fields = topic_fields(topic)
    return {
        "alertId": rec.get("alertId") or rec.get("correlationId") or rec.get("applicationMessageId") or "",
        "topic": topic,
        "site": rec.get("site") or fields["site"],
        "kind": rec.get("kind") or fields["kind"],
        "objectId": str(rec.get("objectId") or fields["objectId"] or ""),
        "receivedAt": rec.get("at") or rec.get("receivedAt"),
        "alertText": rec.get("alertText") or "",
    }


def build_incident_report(
    records: Sequence[dict],
    *,
    current_stats: Optional[dict] = None,
    subscriptions: Optional[Iterable[str]] = None,
    queue_name: str = "",
    window: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Build the tool payload for get_operator_incident_report.

    window: "latest" (default), "overnight" (same as latest), or a lookback
    such as "24h" or "60m".
    """
    now = now or datetime.now().astimezone()
    lookback = _parse_window(window)
    stats = current_stats or {}
    depth = stats.get("spooledMsgCount")
    binds = stats.get("bindCount")
    connected = bool(stats.get("connected")) if "connected" in stats else (binds is not None and int(binds) >= 1)
    subs = [s for s in (subscriptions or []) if s]
    if not subs:
        # Discover from recorded snapshots if the caller did not pass them.
        for rec in records:
            if rec.get("type") == "queue_subscriptions" and rec.get("subscriptions"):
                subs = list(rec["subscriptions"])

    w = latest_window(records, now=now, lookback=lookback)
    if w is None:
        return {
            "incidentRecorded": False,
            "queueName": queue_name or stats.get("queueName") or "",
            "operatorConnected": connected,
            "queueDepth": depth,
            "bindCount": binds,
            "queueDepthSource": "semp" if current_stats is not None else "none",
        }

    start, end = w.get("disconnectedAt"), w.get("reconnectedAt")
    published = [
        _alert_summary(rec)
        for rec in records
        if rec.get("type") == "alert" and _in_window(rec.get("at") or rec.get("receivedAt"), start, end)
    ]
    # Alerts that also appeared in a queue browse during the window, or whose
    # topic matches the operator queue subscription (these are the ones that
    # wait for the operator). Prefer explicit queue_browse records when present.
    browsed_ids = set()
    browsed_topics = []
    peak_depth = 0
    for rec in records:
        if rec.get("type") != "queue_snapshot":
            continue
        if not _in_window(rec.get("at"), start, end) and not (
            end is None and parse_iso(rec.get("at")) and parse_iso(start) and parse_iso(rec.get("at")) >= parse_iso(start)
        ):
            continue
        try:
            peak_depth = max(peak_depth, int(rec.get("queueDepth") or 0))
        except (TypeError, ValueError):
            pass
        for msg in rec.get("messages") or []:
            if not isinstance(msg, dict):
                continue
            aid = msg.get("alertId") or msg.get("correlationId") or msg.get("applicationMessageId") or msg.get("msgId")
            if aid is not None and aid != "":
                browsed_ids.add(str(aid))
            if msg.get("topic"):
                browsed_topics.append(msg["topic"])

    queued = []
    seen = set()
    for alert in published:
        topic = alert.get("topic") or ""
        aid = str(alert.get("alertId") or "")
        matches_sub = topic_matches_any(topic, subs) if subs else False
        in_browse = (aid and aid in browsed_ids) or (topic and topic in browsed_topics)
        if matches_sub or in_browse:
            key = aid or topic
            if key in seen:
                continue
            seen.add(key)
            queued.append(alert)

    # If browse captured IDs we did not see on the Direct path, include them.
    published_ids = {str(a.get("alertId") or "") for a in published}
    for rec in records:
        if rec.get("type") != "queue_snapshot":
            continue
        for msg in rec.get("messages") or []:
            if not isinstance(msg, dict):
                continue
            aid = str(msg.get("alertId") or msg.get("correlationId") or msg.get("applicationMessageId") or "")
            if not aid or aid in published_ids or aid in seen:
                continue
            if not _in_window(rec.get("at"), start, end):
                continue
            summary = _alert_summary({**msg, "at": rec.get("at")})
            queued.append(summary)
            seen.add(aid)

    not_queued = [a for a in published if str(a.get("alertId") or a.get("topic") or "") not in seen]

    if peak_depth == 0:
        # Fall back to the count of queued alerts when no snapshot recorded a peak.
        peak_depth = len(queued)

    queue_empty = depth == 0 if depth is not None else None
    counts_match = peak_depth == len(queued) if peak_depth or queued else (len(queued) == 0)
    delivered = bool((not w.get("open")) and queue_empty and counts_match)

    duration = None
    t0, t1 = parse_iso(start), parse_iso(end) if end else now
    if t0 and t1:
        duration = int((t1 - t0).total_seconds())

    return {
        "incidentRecorded": True,
        "queueName": queue_name or stats.get("queueName") or "",
        "operatorConnected": connected,
        "disconnectWindow": {
            "disconnectedAt": start,
            "reconnectedAt": end,
            "durationSeconds": duration,
            "open": bool(w.get("open")),
        },
        "publishedEventCount": len(published),
        "publishedEvents": published,
        "queuedEventCount": len(queued),
        "queuedEvents": queued,
        "queuedAlertIds": [a.get("alertId") for a in queued],
        "notQueuedEvents": not_queued,
        "peakQueueDepth": peak_depth,
        "queueDepth": depth,
        "bindCount": binds,
        "queueDepthSource": "semp" if current_stats is not None else "history",
        "queueSubscriptions": list(subs),
        "countsMatch": counts_match,
        "queueEmpty": queue_empty,
        "allQueuedMessagesDelivered": delivered,
    }


def _parse_window(window: Optional[str]) -> Optional[timedelta]:
    if not window:
        return None
    text = str(window).strip().lower()
    if text in ("", "latest", "overnight", "recent"):
        return None
    if text.endswith("h") and text[:-1].isdigit():
        return timedelta(hours=int(text[:-1]))
    if text.endswith("m") and text[:-1].isdigit():
        return timedelta(minutes=int(text[:-1]))
    if text.endswith("s") and text[:-1].isdigit():
        return timedelta(seconds=int(text[:-1]))
    if text.isdigit():
        return timedelta(minutes=int(text))
    return None
