"""Read-only Agent Mesh tools for the Operations Watch agent."""
from __future__ import annotations

from typing import Any, Dict, Optional

from .monitor import close_monitor, get_monitor


def init_ops_watch(host_component: Any, init_config: Any = None):
    cfg = init_config if isinstance(init_config, dict) else getattr(init_config, "model_dump", lambda: {})()
    get_monitor(cfg or {})


def cleanup_ops_watch(host_component: Any):
    close_monitor()


async def get_operator_status(
    tool_context: Any = None,
    tool_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return whether the primary operator is currently receiving, and the live depth of its guaranteed queue.

    This tool is read-only. It does not publish, consume, or change broker configuration.
    """
    mon = get_monitor(tool_config or {})
    stats = mon.current_stats()
    return {
        "status": "success",
        "source": "local Solace broker SEMP (read-only)",
        "queueName": mon.queue_name,
        "queueSubscriptions": mon.subscriptions,
        "operatorConnected": bool(stats.get("connected")),
        "bindCount": stats.get("bindCount"),
        "clientCount": stats.get("clientCount"),
        "queueDepth": stats.get("spooledMsgCount"),
        "txUnackedMsgCount": stats.get("txUnackedMsgCount"),
        "listeningSince": mon.started_at.isoformat(timespec="seconds"),
        "directSubscribeError": mon._direct_error or None,
    }


async def get_operator_incident_report(
    window: Optional[str] = None,
    tool_context: Any = None,
    tool_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return the most recent primary-operator disconnect window, the alerts that queued while it was disconnected, and whether they were all delivered after reconnect.

    Args:
        window: Optional lookback, such as "latest", "overnight", "24h", or "60m". Defaults to the most recent disconnect window.
    """
    mon = get_monitor(tool_config or {})
    report = mon.incident_report(window=window)
    report["status"] = "success"
    report["source"] = "local Solace broker SEMP and a Direct observer subscription (read-only)"
    return report
