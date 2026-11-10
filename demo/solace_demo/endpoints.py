"""Reports whether the explicit split client is turned on.

The values are not a cloud proof. validated stays false until someone runs
the real cloud-to-Mac path outside this repository's checks.
"""

from __future__ import annotations

from solace_demo.config import _merged
from solace_demo.split_client import split_enabled


def future_endpoints() -> dict:
    enabled = split_enabled()
    return {
        "publisherHost": _merged("SOLACE_PUBLISHER_HOST", "").strip() if enabled else "",
        "operatorHost": _merged("SOLACE_OPERATOR_HOST", "").strip() if enabled else "",
        "usedByWebServer": enabled,
        "validated": False,
        "managementChanges": False,
    }
