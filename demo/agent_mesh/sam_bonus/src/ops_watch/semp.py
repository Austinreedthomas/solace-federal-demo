"""Read-only SEMP helpers for the primary operator queue and client.

Credentials come from ~/.solace-demo/private/split-client.env (or the
environment) and are never logged or returned.
"""
from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

ENV_PATH = Path.home() / ".solace-demo/private/split-client.env"
VPN_DEFAULT = "default"

# Message-list fields that can identify an alert. Anything else is dropped.
_MSG_KEEP = (
    "msgId",
    "replicationGroupMsgId",
    "attachmentSize",
    "contentSize",
    "deliveryCount",
    "elapsedTime",
    "publisherId",
    "redelivered",
    "destination",
    "topic",
    "correlationId",
    "applicationMessageId",
    "applicationMsgType",
    "msgType",
)


def _load_env() -> None:
    if not ENV_PATH.is_file():
        return
    for raw in ENV_PATH.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :]
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
        os.environ.setdefault(key, val)


def operator_queue_name() -> str:
    _load_env()
    name = (
        os.environ.get("OPS_WATCH_QUEUE")
        or os.environ.get("SOLACE_OPERATOR_QUEUE")
        or ""
    ).strip()
    if not name:
        raise RuntimeError("SOLACE_OPERATOR_QUEUE is not set")
    return name


def operator_username() -> str:
    _load_env()
    return (os.environ.get("SOLACE_OPERATOR_USERNAME") or "").strip()


def operator_vpn() -> str:
    _load_env()
    return (os.environ.get("SOLACE_OPERATOR_VPN") or os.environ.get("SOLACE_BROKER_VPN") or VPN_DEFAULT).strip()


def _semp_context() -> tuple[str, str, ssl.SSLContext]:
    _load_env()
    url = os.environ["SOLACE_OPERATOR_SEMP_URL"].rstrip("/")
    user = os.environ["SOLACE_OPERATOR_SEMP_USERNAME"]
    password = os.environ["SOLACE_OPERATOR_SEMP_PASSWORD"]
    import base64

    tok = base64.b64encode(f"{user}:{password}".encode()).decode()
    ctx = ssl._create_unverified_context()
    return url, tok, ctx


def _request(method: str, path: str, body: Optional[dict] = None) -> tuple[int, Any]:
    url, tok, ctx = _semp_context()
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url + path, data=data, method=method)
    req.add_header("Authorization", f"Basic {tok}")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
            raw = resp.read()
            payload = json.loads(raw) if raw else {}
            return resp.status, payload
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            payload = json.loads(raw) if raw else {"error": exc.reason}
        except json.JSONDecodeError:
            payload = {"error": exc.reason}
        return exc.code, payload


def queue_stats(queue_name: Optional[str] = None) -> Dict[str, Any]:
    """Return live depth, unacked, and bind counts. Does not modify the broker.

    Live depth comes from the monitor /msgs collection. On this broker
    spooledMsgCount is cumulative and is not the live depth. Bind count
    comes from current txFlows.
    """
    queue_name = queue_name or operator_queue_name()
    q = urllib.parse.quote(queue_name, safe="")
    vpn = urllib.parse.quote(operator_vpn(), safe="")
    code, payload = _request("GET", f"/SEMP/v2/monitor/msgVpns/{vpn}/queues/{q}")
    if code != 200:
        raise RuntimeError(f"SEMP monitor {code} for the operator queue")
    data = payload.get("data") or {}
    code, msgs = _request("GET", f"/SEMP/v2/monitor/msgVpns/{vpn}/queues/{q}/msgs?count=100")
    if code != 200:
        raise RuntimeError(f"SEMP msgs {code} for the operator queue")
    current = len(msgs.get("data") or [])
    code, flows = _request("GET", f"/SEMP/v2/monitor/msgVpns/{vpn}/queues/{q}/txFlows")
    if code != 200:
        binds = 0
        flow_clients: List[str] = []
    else:
        flow_data = flows.get("data") or []
        binds = len(flow_data)
        flow_clients = [str(f.get("clientName") or "") for f in flow_data]
    return {
        "queueName": data.get("queueName", queue_name),
        "spooledMsgCount": current,
        "msgSpoolUsage": int(data.get("msgSpoolUsage") or 0),
        "txUnackedMsgCount": int(data.get("txUnackedMsgCount") or 0),
        "bindCount": binds,
        "flowClients": flow_clients,
    }


def list_queue_messages(queue_name: Optional[str] = None) -> List[Dict[str, Any]]:
    """Browse metadata for messages currently on the queue. Does not consume them."""
    queue_name = queue_name or operator_queue_name()
    q = urllib.parse.quote(queue_name, safe="")
    vpn = urllib.parse.quote(operator_vpn(), safe="")
    code, msgs = _request("GET", f"/SEMP/v2/monitor/msgVpns/{vpn}/queues/{q}/msgs?count=100")
    if code != 200:
        raise RuntimeError(f"SEMP msgs {code} for the operator queue")
    out: List[Dict[str, Any]] = []
    for item in msgs.get("data") or []:
        if not isinstance(item, dict):
            continue
        rec = {k: item[k] for k in _MSG_KEEP if k in item and item[k] not in (None, "")}
        # Some brokers nest the destination topic.
        dest = item.get("destination")
        if isinstance(dest, dict):
            topic = dest.get("name") or dest.get("destinationName") or dest.get("topic")
            if topic:
                rec["topic"] = topic
        out.append(rec)
    return out


def queue_subscriptions(queue_name: Optional[str] = None) -> List[str]:
    """Return topic subscriptions on the operator queue. Read-only."""
    queue_name = queue_name or operator_queue_name()
    q = urllib.parse.quote(queue_name, safe="")
    vpn = urllib.parse.quote(operator_vpn(), safe="")
    code, subs = _request("GET", f"/SEMP/v2/config/msgVpns/{vpn}/queues/{q}/subscriptions")
    if code != 200:
        raise RuntimeError(f"SEMP subscriptions {code} for the operator queue")
    return [s.get("subscriptionTopic") for s in (subs.get("data") or []) if s.get("subscriptionTopic")]


def client_connection_count(username: Optional[str] = None) -> int:
    """How many live client connections use the primary operator username."""
    username = (username or operator_username()).strip()
    if not username:
        return 0
    vpn = urllib.parse.quote(operator_vpn(), safe="")
    user = urllib.parse.quote(username, safe="")
    code, payload = _request(
        "GET",
        f"/SEMP/v2/monitor/msgVpns/{vpn}/clients?where=clientUsername=={user}&count=100",
    )
    if code != 200:
        # Fallback: list all and filter (VPN is small in this lab).
        code, payload = _request("GET", f"/SEMP/v2/monitor/msgVpns/{vpn}/clients?count=100")
        if code != 200:
            raise RuntimeError(f"SEMP clients {code}")
        data = [
            c
            for c in (payload.get("data") or [])
            if isinstance(c, dict) and c.get("clientUsername") == username
        ]
        return len(data)
    return len(payload.get("data") or [])
