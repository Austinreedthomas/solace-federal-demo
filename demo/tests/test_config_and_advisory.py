import json
from pathlib import Path

import pytest

from solace_demo.agent_mesh import AdvisoryNotConfigured, advisory_summary, validate_summary_document
from solace_demo.catalog import LAUNCH_ALERT_TEXT, TOPIC_BOTH, alert_body
from solace_demo.config import ConfigError, load_config


def test_dotenv_file_is_read_without_shell_or_printing(monkeypatch, tmp_path, capsys):
    env_file = tmp_path / ".env"
    env_file.write_bytes(
        "\ufeffSOLACE_HOST=tcp://127.0.0.1:15555\r\n"
        "SOLACE_SEMP_URL=http://127.0.0.1:18080\r\n"
        "SOLACE_VPN=default\r\n"
        'export SOLACE_ADMIN_PASSWORD="file-admin-secret"\r\n'
        "SOLACE_PUBLISHER_PASSWORD='file-publisher-secret'\r\n"
        "SOLACE_SUBSCRIBER_PASSWORD = file-subscriber-secret\r\n".encode("utf-8")
    )
    for key in (
        "SOLACE_HOST",
        "SOLACE_SEMP_URL",
        "SOLACE_VPN",
        "SOLACE_ADMIN_PASSWORD",
        "SOLACE_PUBLISHER_PASSWORD",
        "SOLACE_SUBSCRIBER_PASSWORD",
        "SOLACE_ALLOW_REMOTE",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("SOLACE_DOTENV_PATH", str(env_file))
    config = load_config()
    assert config.host == "tcp://127.0.0.1:15555"
    assert config.semp_url == "http://127.0.0.1:18080"
    assert config.vpn == "default"
    assert config.admin_password == "file-admin-secret"
    assert config.publisher_password == "file-publisher-secret"
    assert config.subscriber_password == "file-subscriber-secret"
    from solace_demo.cli import main

    assert main(["config-check"]) == 0
    printed = capsys.readouterr().out
    assert "SOLACE_HOST=tcp://127.0.0.1:15555" in printed
    assert "SOLACE_SEMP_URL=http://127.0.0.1:18080" in printed
    assert "Chosen host mapping: 127.0.0.1:15555 -> container port 55555." in printed
    assert "SOLACE_ADMIN_PASSWORD set=true" in printed
    assert "file-admin-secret" not in printed
    assert "file-publisher-secret" not in printed
    assert "file-subscriber-secret" not in printed


def test_environment_overrides_dotenv_file(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "SOLACE_HOST=tcp://127.0.0.1:15555\n"
        "SOLACE_ADMIN_PASSWORD=from-file\n"
        "SOLACE_PUBLISHER_PASSWORD=from-file\n"
        "SOLACE_SUBSCRIBER_PASSWORD=from-file\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SOLACE_DOTENV_PATH", str(env_file))
    monkeypatch.setenv("SOLACE_HOST", "tcp://127.0.0.1:19999")
    monkeypatch.delenv("SOLACE_ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("SOLACE_PUBLISHER_PASSWORD", raising=False)
    monkeypatch.delenv("SOLACE_SUBSCRIBER_PASSWORD", raising=False)
    config = load_config()
    assert config.host == "tcp://127.0.0.1:19999"
    assert config.admin_password == "from-file"


def test_placeholder_passwords_in_file_are_not_used(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "SOLACE_HOST=tcp://127.0.0.1:15555\n"
        "SOLACE_SEMP_URL=http://127.0.0.1:18080\n"
        "SOLACE_ADMIN_PASSWORD=CHANGE_ME_local_admin\n"
        "SOLACE_PUBLISHER_PASSWORD=CHANGE_ME_publisher\n"
        "SOLACE_SUBSCRIBER_PASSWORD=CHANGE_ME_subscriber\n",
        encoding="utf-8",
    )
    for key in (
        "SOLACE_ADMIN_PASSWORD",
        "SOLACE_PUBLISHER_PASSWORD",
        "SOLACE_SUBSCRIBER_PASSWORD",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("SOLACE_DOTENV_PATH", str(env_file))
    with pytest.raises(ConfigError) as raised:
        load_config()
    text = str(raised.value)
    assert "SOLACE_ADMIN_PASSWORD" in text
    assert "CHANGE_ME_local_admin" not in text


def test_sync_refuses_other_containers_and_bad_passwords(monkeypatch):
    from solace_demo.admin_sync import assert_password_acceptable, sync_admin_password
    from solace_demo.config import LabConfig

    with pytest.raises(ConfigError) as raised:
        assert_password_acceptable("bad password")
    assert "bad password" not in str(raised.value)
    config = LabConfig(
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
    monkeypatch.delenv("SOLACE_SYNC_ALLOW_TEST_CONTAINER", raising=False)
    with pytest.raises(ConfigError) as raised:
        sync_admin_password(config, container="some-other-broker")
    assert "some-other-broker" in str(raised.value)
    assert "labpassword" not in str(raised.value)


def test_web_refuses_ground_station_ports_and_dead_broker_invents_nothing():
    from solace_demo.config import ConfigError, LabConfig
    from solace_demo.live import LiveLab
    from solace_demo.web import assert_safe_web_target, web_port

    config = LabConfig(
        host="tcp://127.0.0.1:55554",
        vpn="default",
        semp_url="http://127.0.0.1:8080",
        admin_user="admin",
        admin_password="local-only",
        publisher_username="ssa-publisher",
        publisher_password="local-only",
        subscriber_username="ssa-subscriber",
        subscriber_password="local-only",
        allow_remote=False,
    )
    with pytest.raises(ConfigError) as raised:
        assert_safe_web_target(config, 8877)
    assert "55554" in str(raised.value) or "8080" in str(raised.value)
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("SOLACE_WEB_PORT", "8080")
    with pytest.raises(ConfigError):
        web_port()
    monkeypatch.undo()
    lab = LiveLab(config)
    result = lab.send("launch-ground1")
    assert result["brokerAccepted"] is False
    assert lab.snapshot()["events"] == []
    assert "Nothing was sent" in result["customerText"]


def test_cloud_mode_and_split_endpoints_do_not_connect(monkeypatch):
    from solace_demo.config import ConfigError, LabConfig
    from solace_demo.endpoints import future_endpoints
    from solace_demo.live import waiting_message_count
    from solace_demo.web import assert_safe_web_target

    monkeypatch.setenv("SOLACE_CLOUD_MODE", "1")
    monkeypatch.setenv("SOLACE_PUBLISHER_HOST", "tcp://203.0.113.10:55443")
    monkeypatch.setenv("SOLACE_OPERATOR_HOST", "tcp://127.0.0.1:55554")
    config = LabConfig(
        host="tcp://127.0.0.1:16555",
        vpn="default",
        semp_url="http://127.0.0.1:19081",
        admin_user="admin",
        admin_password="local-only",
        publisher_username="ssa-publisher",
        publisher_password="local-only",
        subscriber_username="ssa-subscriber",
        subscriber_password="local-only",
        allow_remote=False,
    )
    with pytest.raises(ConfigError) as raised:
        assert_safe_web_target(config, 8877)
    assert "not validated" in str(raised.value)
    assert "local-only" not in str(raised.value)
    split = future_endpoints()
    assert split["usedByWebServer"] is False
    assert split["validated"] is False
    assert split["publisherHost"] == ""
    assert waiting_message_count({"data": {"spooledMsgCount": 4}}) is None
    assert waiting_message_count({"meta": {"count": 0}, "data": []}) == 0
    assert waiting_message_count({"meta": {"count": 1}, "data": [{"msgId": 2}], "spooledMsgCount": 9}) == 1
    assert waiting_message_count({"meta": {"count": 100}, "data": [{}] * 100}) is None


def test_architecture_line_uses_configured_host_and_vpn():
    from solace_demo.scenarios import ARCHITECTURE_BOUNDARIES, architecture_lines

    lines = architecture_lines("tcp://127.0.0.1:15555", "default")
    assert lines[0] == (
        "Lab broker: one local Solace Standard software broker, Message VPN default, SMF on 127.0.0.1:15555."
    )
    assert "55554" not in lines[0]
    assert lines[1:] == ARCHITECTURE_BOUNDARIES
    assert "Not in this lab: Solace Cloud, a static bridge, DMR, a second broker, or Kafka." in lines


def test_missing_passwords_do_not_invent_one(monkeypatch):
    monkeypatch.delenv("SOLACE_ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("SOLACE_PUBLISHER_PASSWORD", raising=False)
    monkeypatch.delenv("SOLACE_SUBSCRIBER_PASSWORD", raising=False)
    with pytest.raises(ConfigError) as raised:
        load_config()
    text = str(raised.value)
    assert "SOLACE_ADMIN_PASSWORD" in text
    assert "CHANGE_ME" not in text
    assert "password=" not in text.lower()


def test_remote_host_is_refused(monkeypatch):
    monkeypatch.setenv("SOLACE_ADMIN_PASSWORD", "local-only")
    monkeypatch.setenv("SOLACE_PUBLISHER_PASSWORD", "local-only")
    monkeypatch.setenv("SOLACE_SUBSCRIBER_PASSWORD", "local-only")
    monkeypatch.setenv("SOLACE_HOST", "tcp://example.invalid:55555")
    with pytest.raises(ConfigError) as raised:
        load_config()
    assert "loopback" in str(raised.value)


def test_loopback_default_vpn_loads(monkeypatch):
    monkeypatch.setenv("SOLACE_ADMIN_PASSWORD", "local-only")
    monkeypatch.setenv("SOLACE_PUBLISHER_PASSWORD", "local-only")
    monkeypatch.setenv("SOLACE_SUBSCRIBER_PASSWORD", "local-only")
    monkeypatch.delenv("SOLACE_HOST", raising=False)
    monkeypatch.delenv("SOLACE_SEMP_URL", raising=False)
    monkeypatch.delenv("SOLACE_VPN", raising=False)
    monkeypatch.delenv("SOLACE_ALLOW_REMOTE", raising=False)
    config = load_config()
    assert config.host == "tcp://127.0.0.1:55554"
    assert config.vpn == "default"
    assert config.semp_url == "http://127.0.0.1:8080"


def test_alert_payload_is_synthetic():
    body = alert_body("routing-both-001", TOPIC_BOTH)
    assert body["synthetic"] is True
    assert body["alertText"] == LAUNCH_ALERT_TEXT == "Launch detected"
    assert body["classificationLabel"] == "unclass"
    assert "25544" in body["objectId"]
    assert "password" not in json.dumps(body).lower()


def test_advisory_refuses_and_schema_accepts_only_the_documented_shape():
    with pytest.raises(AdvisoryNotConfigured):
        advisory_summary(alert_body("advisory-not-run-001", TOPIC_BOTH))
    validate_summary_document(
        {
            "alertId": "advisory-not-run-001",
            "topic": TOPIC_BOTH,
            "advisoryOnly": True,
            "summary": "not generated here",
            "source": "solace-agent-mesh",
        }
    )
    with pytest.raises(ValueError):
        validate_summary_document({"alertId": "x", "advisoryOnly": False})


def test_demo_sources_do_not_name_a_cloud_host():
    root = Path(__file__).resolve().parents[1]
    banned = ("solace.cloud", "messaging.solace", "mr-")
    for path in list(root.rglob("*.py")) + list(root.rglob("*.md")) + list(root.rglob("*.yml")):
        if path.parts[-2:] == ("tests", "test_config_and_advisory.py"):
            continue
        text = path.read_text(encoding="utf-8")
        tokens = ("mr-",) if path.name == "test_split_client.py" else banned
        for token in tokens:
            assert token not in text, f"{path.name} contains {token}"
