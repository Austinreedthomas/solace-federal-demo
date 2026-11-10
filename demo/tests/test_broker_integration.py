"""Runs against a local broker when the lab env is set and SEMP answers.

Skipped otherwise. A skip is not a pass.
"""

from __future__ import annotations

import os

import pytest

from solace_demo.config import ConfigError, load_config
from solace_demo.provision import provision, wait_until_ready
from solace_demo.scenarios import run_access, run_delivery, run_routing
from solace_demo.semp import SempError


def _config():
    if not os.environ.get("SOLACE_ADMIN_PASSWORD"):
        pytest.skip("SOLACE_ADMIN_PASSWORD is not set; broker integration not run")
    try:
        config = load_config()
    except ConfigError as exc:
        pytest.skip(str(exc))
    try:
        wait_until_ready(config, attempts=5, pause_seconds=1)
    except SempError as exc:
        pytest.skip(f"local broker not ready: {exc}")
    return config


def test_three_core_steps_on_local_broker():
    config = _config()
    provision(config)
    routing = run_routing(config)
    access = run_access(config)
    delivery = run_delivery(config)
    failures = [report.name for report in (routing, access, delivery) if not report.passed]
    details = "\n".join(line for report in (routing, access, delivery) for line in [f"== {report.name} =="] + report.lines)
    assert not failures, details
