"""Optional simulated weather reading published with MQTT.

The browser button is HTTP. This process is the MQTT client. The operator
receives the same payload with SMF. Solace carries MQTT QoS 0 as Direct.
This module does not translate protocols and does not invent a receipt.
"""

from __future__ import annotations

import json
import ssl
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from solace_demo.catalog import WEATHER_TOPIC, alert_body
from solace_demo.config import ConfigError, _flag, _merged, _usable

WEATHER_TEXT = (
    "Published one MQTT QoS 0 reading. Solace carries QoS 0 as Direct. "
    "The operator shows it when the SMF subscriber receives this same id."
)


@dataclass
class WeatherSettings:
    enabled: bool
    scheme: str = ""
    host: str = ""
    port: int = 0
    username: str = ""
    password: str = ""
    trust_file: str = ""
    problem: str = ""

    def target(self) -> str:
        if not self.host or not self.port:
            return ""
        return f"{self.host}:{self.port}"


def _bad(text: str) -> None:
    raise ConfigError(text)


def _loopback(hostname: str) -> bool:
    return (hostname or "").lower() in {"127.0.0.1", "localhost", "::1"}


def _has_control(value: str) -> bool:
    return any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in value)


def load_weather() -> WeatherSettings:
    """Off unless SOLACE_MQTT_WEATHER=1. A bad setting does not stop the other demos."""
    if not _flag("SOLACE_MQTT_WEATHER"):
        return WeatherSettings(enabled=False)
    try:
        return _load_enabled()
    except ConfigError as exc:
        return WeatherSettings(enabled=False, problem=str(exc))


def parse_mqtt_target(raw: str) -> tuple:
    """Return scheme, host, and port. The error does not repeat raw."""
    if not raw or _has_control(raw):
        _bad("SOLACE_MQTT_URL must be mqtt:// or mqtts:// with a host and a port, and no whitespace or control character.")
    parsed = urlparse(raw)
    tail = raw.split("://", 1)[-1]
    if parsed.username or parsed.password or "@" in tail or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        _bad("SOLACE_MQTT_URL must not include a username, password, path, or query.")
    if parsed.scheme not in {"mqtt", "mqtts"} or not parsed.hostname or not parsed.port:
        _bad("SOLACE_MQTT_URL must be mqtt:// or mqtts:// with a host and a port.")
    if parsed.scheme == "mqtt" and not _loopback(parsed.hostname):
        _bad("SOLACE_MQTT_URL refuses cleartext outside 127.0.0.1, localhost, or ::1. Use mqtts://.")
    return parsed.scheme, parsed.hostname, parsed.port


def _load_enabled() -> WeatherSettings:
    scheme, hostname, port = parse_mqtt_target(_usable(_merged("SOLACE_MQTT_URL", "")))
    auth = _usable(_merged("SOLACE_MQTT_AUTH", "")).lower()
    if auth in {"no-auth", "noauth"}:
        auth = "none"
    if auth not in {"", "password", "none"}:
        _bad("SOLACE_MQTT_AUTH must be password or none.")
    username = _usable(_merged("SOLACE_MQTT_USERNAME", ""))
    password = _usable(_merged("SOLACE_MQTT_PASSWORD", ""))
    trust = _usable(_merged("SOLACE_MQTT_TRUST_FILE", ""))
    if _has_control(username) or _has_control(trust):
        _bad("SOLACE_MQTT_USERNAME and SOLACE_MQTT_TRUST_FILE must not contain whitespace or control characters.")
    passwordless = auth == "none"
    if passwordless and (scheme != "mqtt" or not _loopback(hostname)):
        _bad("SOLACE_MQTT_AUTH=none is only allowed for a loopback mqtt:// URL.")
    if passwordless and password:
        _bad("SOLACE_MQTT_AUTH=none does not take a password. Remove SOLACE_MQTT_PASSWORD.")
    if not passwordless and not (username and password):
        _bad("SOLACE_MQTT_USERNAME and SOLACE_MQTT_PASSWORD are required. Weather does not reuse another client.")
    if scheme == "mqtts":
        if not trust or not Path(trust).is_file():
            _bad("SOLACE_MQTT_TRUST_FILE must be a PEM file for mqtts://. Certificate checks stay on.")
    elif trust:
        _bad("SOLACE_MQTT_TRUST_FILE is only used with mqtts://.")
    return WeatherSettings(True, scheme, hostname, port, username, "" if passwordless else password, trust)


def publish_weather(settings: WeatherSettings, alert_id: str, body: dict, topic: str = WEATHER_TOPIC) -> None:
    """Hand one QoS 0 MQTT publish to the socket. That is not a broker acknowledgement."""
    try:
        import paho.mqtt.client as mqtt
    except ImportError as exc:
        raise RuntimeError("The MQTT client library is not installed.") from exc
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="ssa-weather-" + uuid.uuid4().hex[:8])
    if settings.username:
        client.username_pw_set(settings.username, settings.password or None)
    if settings.scheme == "mqtts":
        client.tls_set(ca_certs=settings.trust_file, cert_reqs=ssl.CERT_REQUIRED, tls_version=ssl.PROTOCOL_TLS_CLIENT)
    client.connect(settings.host, settings.port, keepalive=10)
    client.loop_start()
    try:
        info = client.publish(topic, json.dumps(body, separators=(",", ":"), sort_keys=True), qos=0, retain=False)
        info.wait_for_publish(timeout=5)
        if not info.is_published():
            raise TimeoutError("The MQTT client did not hand the reading to the socket.")
    finally:
        client.loop_stop()
        client.disconnect()


def weather_body(alert_id: str, topic: str = WEATHER_TOPIC) -> dict:
    body = alert_body(alert_id, topic)
    body["simulated"] = True
    body["temperatureC"] = 18
    body["windKph"] = 12
    body["note"] = "Weather sample."
    return body
