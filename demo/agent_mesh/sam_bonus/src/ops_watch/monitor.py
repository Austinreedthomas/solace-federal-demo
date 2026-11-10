"""Read-only monitor for the primary operator and its guaranteed queue.

Records (and never publishes or consumes from the operator queue):
  - operator bind / client connect-disconnect via SEMP
  - live queue depth and a browse of spooled message metadata via SEMP
  - alerts on configured topics via a Direct subscription

History is a JSONL file so the agent tools can report a disconnect window
after the operator has already reconnected and the queue has drained.
"""
from __future__ import annotations

import collections
import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path

from solace.messaging.receiver.message_receiver import MessageHandler

from .report import build_incident_report
from .semp import (
    client_connection_count,
    list_queue_messages,
    operator_queue_name,
    operator_username,
    queue_stats,
    queue_subscriptions,
    _load_env,
)

_LOCK = threading.Lock()
_MONITOR = None

DEFAULT_HISTORY = Path(__file__).resolve().parents[2] / "data" / "ops-watch.jsonl"
DEFAULT_STATE = Path(__file__).resolve().parents[2] / "data" / "ops-watch-state.json"
MAX_RECORDS = 2000
POLL_SECONDS = 0.5


def _now() -> datetime:
    return datetime.now().astimezone()


def _iso(ts: datetime | None = None) -> str:
    return (ts or _now()).isoformat(timespec="seconds")


class _DirectHandler(MessageHandler):
    def __init__(self, monitor: "OpsMonitor"):
        self.m = monitor

    def on_message(self, message):
        try:
            self.m._ingest_direct(message)
        except Exception:
            pass


class OpsMonitor:
    def __init__(
        self,
        history_path=None,
        state_path=None,
        queue_name=None,
        subscriptions=None,
        poll_seconds=POLL_SECONDS,
        start_direct=True,
    ):
        self.records = collections.deque(maxlen=MAX_RECORDS)
        self.history_path = Path(history_path or os.environ.get("OPS_WATCH_HISTORY", DEFAULT_HISTORY))
        self.state_path = Path(state_path or os.environ.get("OPS_WATCH_STATE", DEFAULT_STATE))
        self.poll_seconds = poll_seconds
        self.started_at = _now()
        self._closing = False
        self._stop = threading.Event()
        self._direct_error = ""
        self.service = None
        self.receiver = None
        self._load_history()
        _load_env()
        self.queue_name = queue_name or os.environ.get("OPS_WATCH_QUEUE") or operator_queue_name()
        self.username = operator_username()
        try:
            self.subscriptions = list(subscriptions) if subscriptions else queue_subscriptions(self.queue_name)
        except Exception:
            self.subscriptions = list(subscriptions or [])
        self._append(
            {
                "type": "queue_subscriptions",
                "at": _iso(),
                "queueName": self.queue_name,
                "subscriptions": self.subscriptions,
            }
        )
        self._last_bound: bool | None = None
        self._last_depth: int | None = None
        self._last_connected: bool | None = None
        if start_direct:
            self._start_direct()
        self._poll_thread = threading.Thread(target=self._poll_loop, name="ops-watch-poll", daemon=True)
        self._poll_thread.start()
        self._write_state(status="running")

    def _load_history(self) -> None:
        if not self.history_path.is_file():
            return
        try:
            lines = self.history_path.read_text().splitlines()
        except OSError:
            return
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(rec, dict):
                self.records.append(rec)

    def _append(self, rec: dict) -> None:
        rec.setdefault("at", _iso())
        self.records.append(rec)
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        with self.history_path.open("a") as fh:
            fh.write(json.dumps(rec, separators=(",", ":")) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    def _write_state(self, status: str, **extra) -> None:
        state = {
            "status": status,
            "pid": os.getpid(),
            "queueName": getattr(self, "queue_name", ""),
            "lastSeenAt": _iso(),
            "startedAt": _iso(self.started_at),
        }
        state.update(extra)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2) + "\n")
        tmp.replace(self.state_path)

    def _start_direct(self) -> None:
        """Subscribe Direct to observe alerts without binding the operator queue."""
        _load_env()
        host = os.environ.get("SOLACE_BROKER_URL") or os.environ.get("SOLACE_OPERATOR_HOST") or ""
        vpn = os.environ.get("SOLACE_BROKER_VPN") or os.environ.get("SOLACE_OPERATOR_VPN") or "default"
        username = os.environ.get("SOLACE_BROKER_USERNAME") or "sam-bonus-mesh"
        password = os.environ.get("SOLACE_BROKER_PASSWORD") or ""
        if not host:
            self._direct_error = "no-broker-url"
            self._append({"type": "service", "kind": "direct-subscribe-skipped", "reason": "no-broker-url"})
            return
        # Observe both the live ssa/unclass tree and the guaranteed prefix tree.
        topics = ["ssa/unclass/>"]
        prefix = (os.environ.get("SOLACE_GUARANTEED_TOPIC_PREFIX") or "").strip().rstrip("/")
        if prefix and prefix != "ssa/unclass":
            topics.append(prefix + "/>")
        for sub in self.subscriptions:
            if sub and sub not in topics:
                topics.append(sub)
        try:
            from solace.messaging.messaging_service import MessagingService
            from solace.messaging.resources.topic_subscription import TopicSubscription

            props = {
                "solace.messaging.transport.host": host,
                "solace.messaging.service.vpn-name": vpn,
                "solace.messaging.authentication.scheme.basic.username": username,
                "solace.messaging.authentication.scheme.basic.password": password or "",
                "solace.messaging.client.name": f"sam-bonus-ops-watch-{os.getpid()}",
            }
            self.service = MessagingService.builder().from_properties(props).build()
            self.service.connect()
            builder = self.service.create_direct_message_receiver_builder()
            self.receiver = builder.with_subscriptions(
                [TopicSubscription.of(t) for t in topics]
            ).build()
            self.receiver.start()
            self.receiver.receive_async(_DirectHandler(self))
            self._append({"type": "service", "kind": "direct-subscribed", "topics": topics})
        except Exception as exc:
            self._direct_error = type(exc).__name__
            self._append(
                {
                    "type": "service",
                    "kind": "direct-subscribe-failed",
                    "reason": type(exc).__name__,
                }
            )

    def _ingest_direct(self, message) -> None:
        topic = ""
        try:
            topic = message.get_destination_name() or ""
        except Exception:
            topic = ""
        raw = None
        try:
            raw = message.get_payload_as_string()
        except Exception:
            raw = None
        if raw is None:
            try:
                b = message.get_payload_as_bytes()
                raw = b.decode("utf-8", "replace") if b else ""
            except Exception:
                raw = ""
        try:
            body = json.loads(raw) if raw else {}
            if not isinstance(body, dict):
                body = {"value": body}
        except json.JSONDecodeError:
            body = {"text": (raw or "")[:500]}
        parts = topic.split("/")
        alert_id = ""
        try:
            alert_id = body.get("alertId") or message.get_correlation_id() or ""
        except Exception:
            alert_id = body.get("alertId") or ""
        rec = {
            "type": "alert",
            "at": _iso(),
            "topic": topic,
            "site": body.get("site") or (parts[2] if len(parts) > 2 else ""),
            "kind": body.get("kind") or (parts[3] if len(parts) > 3 else ""),
            "objectId": str(body.get("objectId") or (parts[4] if len(parts) > 4 else "")),
            "alertId": alert_id,
            "alertText": body.get("alertText") or body.get("text") or "",
            "classificationLabel": body.get("classificationLabel", ""),
            "synthetic": body.get("synthetic", None),
        }
        self._append(rec)

    def _poll_once(self) -> dict:
        stats = queue_stats(self.queue_name)
        try:
            clients = client_connection_count(self.username) if self.username else None
        except Exception:
            clients = None
        bound = int(stats.get("bindCount") or 0) >= 1
        depth = int(stats.get("spooledMsgCount") or 0)
        connected = bound if clients is None else (bound or clients >= 1)
        # Prefer bind count as the "operator is receiving from this queue" signal.
        receiving = bound
        messages = []
        if depth > 0:
            try:
                messages = list_queue_messages(self.queue_name)
            except Exception:
                messages = []
        snapshot = {
            "queueName": self.queue_name,
            "queueDepth": depth,
            "bindCount": int(stats.get("bindCount") or 0),
            "clientCount": clients,
            "connected": receiving,
            "txUnackedMsgCount": int(stats.get("txUnackedMsgCount") or 0),
        }
        edge = self._last_bound is not None and receiving != self._last_bound
        if edge:
            kind = "reconnected" if receiving else "disconnected"
            self._append(
                {
                    "type": "operator_event",
                    "kind": kind,
                    "at": _iso(),
                    "bindCount": snapshot["bindCount"],
                    "queueDepth": depth,
                    "clientCount": clients,
                }
            )
        if edge or depth != self._last_depth:
            rec = {
                "type": "queue_snapshot",
                "at": _iso(),
                "queueDepth": depth,
                "bindCount": snapshot["bindCount"],
                "messages": messages,
            }
            self._append(rec)
        self._last_bound = receiving
        self._last_depth = depth
        self._last_connected = receiving
        try:
            self._write_state(status="running", **snapshot)
        except Exception:
            pass
        snapshot["messages"] = messages
        return snapshot

    def _poll_loop(self) -> None:
        # Prime last_bound without emitting a synthetic event on startup.
        try:
            stats = queue_stats(self.queue_name)
            self._last_bound = int(stats.get("bindCount") or 0) >= 1
            self._last_depth = int(stats.get("spooledMsgCount") or 0)
            self._write_state(
                status="running",
                queueDepth=self._last_depth,
                bindCount=int(stats.get("bindCount") or 0),
                connected=self._last_bound,
            )
        except Exception:
            pass
        while not self._stop.wait(self.poll_seconds):
            if self._closing:
                return
            try:
                self._poll_once()
            except Exception:
                pass

    def current_stats(self) -> dict:
        try:
            stats = queue_stats(self.queue_name)
        except Exception:
            stats = {
                "queueName": self.queue_name,
                "spooledMsgCount": self._last_depth,
                "bindCount": 1 if self._last_bound else 0,
            }
        try:
            clients = client_connection_count(self.username) if self.username else None
        except Exception:
            clients = None
        bound = int(stats.get("bindCount") or 0) >= 1
        stats["connected"] = bound
        stats["clientCount"] = clients
        return stats

    def incident_report(self, window: str | None = None) -> dict:
        return build_incident_report(
            list(self.records),
            current_stats=self.current_stats(),
            subscriptions=self.subscriptions,
            queue_name=self.queue_name,
            window=window,
            now=_now(),
        )

    def close(self) -> None:
        self._closing = True
        self._stop.set()
        try:
            self._write_state(status="stopped")
        except Exception:
            pass
        try:
            if self.receiver is not None:
                self.receiver.terminate()
        except Exception:
            pass
        try:
            if self.service is not None:
                self.service.disconnect()
        except Exception:
            pass


def get_monitor(cfg=None) -> OpsMonitor:
    global _MONITOR
    with _LOCK:
        if _MONITOR is None:
            cfg = cfg or {}
            _MONITOR = OpsMonitor(
                history_path=cfg.get("history_path"),
                state_path=cfg.get("state_path"),
                queue_name=cfg.get("queue_name"),
                subscriptions=cfg.get("subscriptions"),
                start_direct=cfg.get("start_direct", True),
            )
        return _MONITOR


def close_monitor() -> None:
    global _MONITOR
    with _LOCK:
        if _MONITOR is not None:
            _MONITOR.close()
            _MONITOR = None
