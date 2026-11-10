"""Optional Agent Mesh seam. This module does not call a model."""

from __future__ import annotations

from typing import Any


class AdvisoryNotConfigured(RuntimeError):
    """A validated Agent Mesh runtime is not part of this demo."""


SUMMARY_FIELDS = ("alertId", "topic", "advisoryOnly", "summary", "source")


def validate_summary_document(document: dict[str, Any]) -> None:
    """Check the shape we would accept from a future Agent Mesh runtime."""
    extra = set(document) - set(SUMMARY_FIELDS)
    missing = [field for field in SUMMARY_FIELDS if field not in document]
    if missing or extra:
        raise ValueError(f"summary document fields missing={missing} extra={sorted(extra)}")
    if document["advisoryOnly"] is not True:
        raise ValueError("advisoryOnly must be true")
    if document["source"] != "solace-agent-mesh":
        raise ValueError("source must be solace-agent-mesh")
    for field in ("alertId", "topic", "summary"):
        if not isinstance(document[field], str) or not document[field]:
            raise ValueError(f"{field} must be a non-empty string")


def advisory_summary(alert: dict[str, Any]) -> dict[str, Any]:
    """Refuse to invent a summary.

    Core delivery does not call this. There is no model client in this package.
    """
    if not alert.get("alertId") or not alert.get("topic"):
        raise ValueError("alert is missing alertId or topic")
    raise AdvisoryNotConfigured(
        "Solace Agent Mesh is not installed or validated in this demo. "
        "Licensing, the runtime build, and any model endpoint are unresolved. "
        "No summary was generated."
    )
