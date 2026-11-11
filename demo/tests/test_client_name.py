"""Optional SOLACE_CLIENT_NAME applies only to the publisher SMF session."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from solace.messaging.config.solace_properties import client_properties

from solace_demo.config import LabConfig, publisher_client_name
from solace_demo.live import LiveLab, WEB_TRANSPORT
from solace_demo.messaging import with_publisher_client_name


NAME = client_properties.NAME


def _config() -> LabConfig:
    return LabConfig(
        host="tcp://127.0.0.1:15555",
        vpn="default",
        semp_url="http://127.0.0.1:18080",
        admin_user="admin",
        admin_password="labpassword",
        publisher_username="ssa-publisher",
        publisher_password="labpassword",
        subscriber_username="ssa-subscriber",
        subscriber_password="labpassword",
        allow_remote=False,
    )


def _clear_name(monkeypatch, tmp_path):
    monkeypatch.setenv("SOLACE_DOTENV_PATH", str(tmp_path / "empty.env"))
    monkeypatch.delenv("SOLACE_CLIENT_NAME", raising=False)


def test_publisher_client_name_unset_leaves_auto_generated_name(monkeypatch, tmp_path):
    _clear_name(monkeypatch, tmp_path)
    assert publisher_client_name() == ""
    props = with_publisher_client_name(WEB_TRANSPORT)
    assert NAME not in props
    assert props == dict(WEB_TRANSPORT)


def test_publisher_client_name_blank_or_placeholder_is_treated_as_unset(monkeypatch, tmp_path):
    _clear_name(monkeypatch, tmp_path)
    monkeypatch.setenv("SOLACE_CLIENT_NAME", "   ")
    assert publisher_client_name() == ""
    assert NAME not in with_publisher_client_name({"keep": "me"})
    monkeypatch.setenv("SOLACE_CLIENT_NAME", "CHANGE_ME_publisher_name")
    assert publisher_client_name() == ""


def test_publisher_client_name_is_applied_when_set(monkeypatch, tmp_path):
    _clear_name(monkeypatch, tmp_path)
    monkeypatch.setenv("SOLACE_CLIENT_NAME", "  demo-publisher  ")
    assert publisher_client_name() == "demo-publisher"
    props = with_publisher_client_name({"solace.messaging.transport.host": "tcp://127.0.0.1:15555"})
    assert props[NAME] == "demo-publisher"
    assert props["solace.messaging.transport.host"] == "tcp://127.0.0.1:15555"


def test_dotenv_can_set_publisher_client_name_and_env_wins(monkeypatch, tmp_path):
    env_file = tmp_path / "client.env"
    env_file.write_text("SOLACE_CLIENT_NAME=from-file\n", encoding="utf-8")
    monkeypatch.setenv("SOLACE_DOTENV_PATH", str(env_file))
    monkeypatch.delenv("SOLACE_CLIENT_NAME", raising=False)
    assert publisher_client_name() == "from-file"
    monkeypatch.setenv("SOLACE_CLIENT_NAME", "from-env")
    assert publisher_client_name() == "from-env"


def test_open_sessions_sets_client_name_on_publisher_only(monkeypatch, tmp_path):
    _clear_name(monkeypatch, tmp_path)
    monkeypatch.setenv("SOLACE_CLIENT_NAME", "demo-publisher")
    captured = []

    def fake_connect(config, username, password, properties=None):
        captured.append((username, dict(properties or {})))
        return SimpleNamespace()

    lab = LiveLab(_config(), role="all")
    with patch("solace_demo.live.connect", fake_connect), patch.object(
        LiveLab, "_ensure_publishers", lambda self: None
    ):
        lab._open_sessions_locked()

    names = {username: props for username, props in captured}
    assert names["ssa-publisher"][NAME] == "demo-publisher"
    assert NAME not in names["ssa-subscriber"]
    assert set(names) == {"ssa-publisher", "ssa-subscriber"}


def test_operator_session_does_not_receive_publisher_client_name(monkeypatch, tmp_path):
    _clear_name(monkeypatch, tmp_path)
    monkeypatch.setenv("SOLACE_CLIENT_NAME", "demo-publisher")
    captured = []

    def fake_connect(config, username, password, properties=None):
        captured.append((username, dict(properties or {})))
        return SimpleNamespace()

    lab = LiveLab(_config(), role="operators")
    with patch("solace_demo.live.connect", fake_connect), patch.object(
        LiveLab, "_ensure_publishers", lambda self: None
    ):
        lab._open_sessions_locked()

    assert captured[0][0] == "ssa-subscriber"
    assert NAME not in captured[0][1]
    assert len(captured) == 1
