"""Optional MQTT weather stays off, and it does not borrow another client."""

import os

import pytest

from solace_demo.config import ConfigError
from solace_demo.mqtt_weather import load_weather, parse_mqtt_target


def _clear(monkeypatch):
    for name in (
        "SOLACE_MQTT_WEATHER",
        "SOLACE_MQTT_URL",
        "SOLACE_MQTT_USERNAME",
        "SOLACE_MQTT_PASSWORD",
        "SOLACE_MQTT_TRUST_FILE",
        "SOLACE_MQTT_AUTH",
        "SOLACE_PUBLISHER_USERNAME",
        "SOLACE_PUBLISHER_PASSWORD",
    ):
        monkeypatch.delenv(name, raising=False)


def test_weather_is_off_unless_requested(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("SOLACE_PUBLISHER_PASSWORD", "cloud-secret")
    assert load_weather().enabled is False
    assert load_weather().problem == ""


def test_weather_does_not_reuse_another_client(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("SOLACE_MQTT_WEATHER", "1")
    monkeypatch.setenv("SOLACE_MQTT_URL", "mqtt://127.0.0.1:1883")
    monkeypatch.setenv("SOLACE_PUBLISHER_USERNAME", "cloud-client")
    monkeypatch.setenv("SOLACE_PUBLISHER_PASSWORD", "cloud-secret")
    settings = load_weather()
    assert settings.enabled is False
    assert "cloud-secret" not in settings.problem
    assert "SOLACE_MQTT_USERNAME" in settings.problem


def test_mqtt_url_refuses_remote_cleartext_and_control_characters(monkeypatch, tmp_path):
    _clear(monkeypatch)
    monkeypatch.setenv("SOLACE_MQTT_WEATHER", "1")
    monkeypatch.setenv("SOLACE_MQTT_USERNAME", "weather-user")
    monkeypatch.setenv("SOLACE_MQTT_PASSWORD", "weather-secret")
    monkeypatch.setenv("SOLACE_MQTT_URL", "mqtt://203.0.113.10:1883")
    refused = load_weather()
    assert refused.enabled is False
    assert "203.0.113.10" not in refused.problem
    assert "weather-secret" not in refused.problem
    for raw in (
        "mqtt://127.0.0.1:1883\nbad",
        "mqtt://127.0.0.1:1883\rbad",
        "mqtt://127.0.0.1\x00:1883",
        "mqtt://127.0.0.1\x01:1883",
        "mqtt://127.0.0.1\x7f:1883",
    ):
        with pytest.raises(ConfigError) as raised:
            parse_mqtt_target(raw)
        text = str(raised.value)
        assert raw not in text
        assert all(ch not in text for ch in raw if ch.isspace() or ord(ch) < 32 or ord(ch) == 127)
    trust = tmp_path / "ca.pem"
    trust.write_text("not-a-real-certificate\n", encoding="utf-8")
    monkeypatch.setenv("SOLACE_MQTT_URL", "mqtts://127.0.0.1")
    missing_port = load_weather()
    assert missing_port.enabled is False
    monkeypatch.setenv("SOLACE_MQTT_URL", "mqtts://127.0.0.1:8883")
    monkeypatch.setenv("SOLACE_MQTT_TRUST_FILE", str(trust))
    ready = load_weather()
    assert ready.enabled is True
    assert ready.port == 8883
    assert ready.scheme == "mqtts"


def test_mqtt_qos0_is_received_on_the_smf_subscription():
    if not os.environ.get("SOLACE_ADMIN_PASSWORD") or not os.environ.get("SOLACE_TEST_MQTT_URL"):
        pytest.skip("SOLACE_TEST_MQTT_URL is not set; MQTT broker integration not run")
    import time

    from solace_demo.catalog import WEATHER_TOPIC
    from solace_demo.config import load_config
    from solace_demo.live import LiveLab
    from solace_demo.provision import ensure_web_queue, provision
    from solace_demo.semp import Semp

    config = load_config()
    provision(config)
    ensure_web_queue(Semp(config), config)
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("SOLACE_MQTT_WEATHER", "1")
    monkeypatch.setenv("SOLACE_MQTT_URL", os.environ["SOLACE_TEST_MQTT_URL"])
    monkeypatch.setenv("SOLACE_MQTT_USERNAME", config.publisher_username)
    monkeypatch.setenv("SOLACE_MQTT_PASSWORD", config.publisher_password)
    lab = LiveLab(config)
    lab.open()
    try:
        result = lab.send("weather")
        assert result["outcome"] == "sent"
        assert result["brokerAck"] is False
        assert result["topic"] == WEATHER_TOPIC
        assert "25544" not in result["topic"]
        found = None
        for _ in range(25):
            for event in lab.snapshot()["events"]:
                if event.get("alertId") == result["alertId"]:
                    found = event
                    break
            if found:
                break
            time.sleep(0.2)
        assert found is not None
        assert found["feed"] == "weather-ground1"
        assert found["origin"] == "this-session"
        assert found["topic"] == WEATHER_TOPIC
        assert found["alertText"] == "Weather reading"
    finally:
        lab.close()
        monkeypatch.undo()
