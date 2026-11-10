"""Loopback pages for the publisher and the operator console.

Broker passwords stay in this process. The browser only receives alert ids,
topics, and broker results.
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from solace_demo.catalog import QUEUE_NAME, WEB_QUEUE_NAME
from solace_demo.config import ConfigError, LabConfig, load_config
from solace_demo.live import LiveLab
from solace_demo.messaging import safe_error
from solace_demo.provision import ensure_web_queue, provision
from solace_demo.semp import Semp
from solace_demo.split_client import load_split_client, split_enabled
from permissions_demo import web_attempt

WEB_ROOT = Path(__file__).resolve().parent.parent / "web"
FORBIDDEN_WEB_PORTS = {8080, 55554, 55555, 15555, 18080}
GROUND_STATION_PORTS = {55554, 8080}


def _redact(text: str, config: LabConfig, extra_secrets: tuple = ()) -> str:
    secrets = [config.admin_password, config.publisher_password, config.subscriber_password, config.admin_user]
    secrets.extend(extra_secrets)
    for secret in secrets:
        if secret and secret not in {"admin"}:
            text = text.replace(secret, "[redacted]")
    return text[:240]


def public_payload(payload: dict, config: LabConfig, extra_secrets: tuple = ()) -> dict:
    """Redact secrets in every string the browser can receive."""

    def walk(value):
        if isinstance(value, str):
            return _redact(value, config, extra_secrets)
        if isinstance(value, dict):
            return {str(key): walk(item) for key, item in value.items()}
        if isinstance(value, list):
            return [walk(item) for item in value]
        return value

    cleaned = walk(payload)
    if not isinstance(cleaned, dict):
        return {"customerText": "Request blocked."}
    return cleaned


def web_role() -> str:
    raw = os.environ.get("SOLACE_WEB_ROLE", "all").strip().lower() or "all"
    if raw not in {"all", "publisher", "operators"}:
        raise ConfigError("SOLACE_WEB_ROLE must be all, publisher, or operators.")
    return raw


def web_bind_host() -> str:
    raw = os.environ.get("SOLACE_WEB_HOST", "127.0.0.1").strip() or "127.0.0.1"
    if any(ord(ch) < 32 or ord(ch) == 127 or ch.isspace() for ch in raw):
        raise ConfigError("SOLACE_WEB_HOST must be a host or address without whitespace.")
    if "://" in raw or "/" in raw or "@" in raw or ":" in raw:
        raise ConfigError("SOLACE_WEB_HOST must be a host or address without a scheme, port, or path.")
    return raw


def home_path(role: str) -> str:
    if role == "operators":
        return "/operator"
    return "/publisher"


_PAGE_GET = {"/publisher", "/operator", "/restricted-operator", "/app.css", "/operator-status.js", "/api/state"}
_ROLE_GET = {
    "all": _PAGE_GET,
    "publisher": {"/publisher", "/app.css", "/api/state"},
    "operators": {"/operator", "/restricted-operator", "/app.css", "/operator-status.js", "/api/state"},
}
_ROLE_POST = {
    "all": {"/api/send", "/api/permissions", "/api/listen", "/api/clear"},
    "publisher": {"/api/send"},
    "operators": {"/api/listen", "/api/permissions", "/api/clear"},
}


def filter_nav(html: str, role: str) -> str:
    if role == "all":
        return html
    kept = []
    for line in html.splitlines(keepends=True):
        if "data-role=" in line and f'data-role="{role}"' not in line:
            continue
        kept.append(line)
    return "".join(kept)


def web_port() -> int:
    raw = os.environ.get("SOLACE_WEB_PORT", "8877").strip() or "8877"
    port = int(raw)
    if port in FORBIDDEN_WEB_PORTS or not (1 <= port <= 65535):
        raise ConfigError(
            f"SOLACE_WEB_PORT {port} is not available for the demo pages. "
            "Use a free port other than 8080, 55554, 55555, 15555, or 18080."
        )
    return port


def assert_safe_web_target(config, port: int) -> None:
    web_port_value = port
    if web_port_value in FORBIDDEN_WEB_PORTS:
        raise ConfigError("Refusing to bind the demo pages to a broker port.")
    cloud = os.environ.get("SOLACE_CLOUD_MODE", "").strip().lower() in {"1", "true", "yes"}
    if config.allow_remote and not cloud:
        raise ConfigError(
            "Refusing a non-loopback broker. Set SOLACE_CLOUD_MODE=1 only for a path "
            "you intend to test. That path is not validated yet, and this server will "
            "not change a remote broker's configuration."
        )
    if cloud:
        raise ConfigError(
            "Cloud mode is not validated. This server will not connect to a remote broker "
            "or change the ground station. Keep SOLACE_ALLOW_REMOTE unset and use the isolated lab."
        )
    host_port = urlparse(config.host if "://" in config.host else f"tcp://{config.host}").port
    semp_port = urlparse(config.semp_url).port
    if host_port in GROUND_STATION_PORTS or semp_port in GROUND_STATION_PORTS:
        raise ConfigError(
            "Refusing host port 55554 or SEMP port 8080. Those belong to the existing "
            "ground-station broker. Point SOLACE_HOST and SOLACE_SEMP_URL at the isolated lab."
        )


class DemoHandler(BaseHTTPRequestHandler):
    # Chrome leaves a fetch unfinished against this library's default HTTP/1.0 responses.
    protocol_version = "HTTP/1.1"
    lab: LiveLab
    port: int
    bind_host: str = "127.0.0.1"

    def log_message(self, fmt: str, *args) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        role = web_role()
        if path == "/":
            self._redirect(home_path(role))
            return
        if path not in _ROLE_GET[role]:
            self._missing(path)
            return
        if path == "/publisher":
            self._file("publisher.html", "text/html; charset=utf-8")
        elif path == "/operator":
            self._file("operator.html", "text/html; charset=utf-8")
        elif path == "/restricted-operator":
            self._file("restricted-operator.html", "text/html; charset=utf-8")
        elif path == "/app.css":
            self._file("app.css", "text/css; charset=utf-8")
        elif path == "/operator-status.js":
            self._file("operator-status.js", "text/javascript; charset=utf-8")
        elif path == "/api/state":
            self._json(self.lab.snapshot())
        else:
            self._missing(path)

    def do_POST(self) -> None:  # noqa: N802
        if not self._same_origin():
            self._json({"customerText": "Request blocked.", "brokerAccepted": False}, status=403)
            return
        path = urlparse(self.path).path
        if path not in _ROLE_POST[web_role()]:
            self._missing(path)
            return
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length > 2000:
            self._json({"customerText": "Request blocked.", "brokerAccepted": False}, status=400)
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._json({"customerText": "Request blocked.", "brokerAccepted": False}, status=400)
            return
        if not isinstance(payload, dict):
            self._json({"customerText": "Request blocked.", "brokerAccepted": False}, status=400)
            return
        try:
            if path == "/api/send":
                result = self.lab.send(str(payload.get("kind") or ""))
            elif path == "/api/permissions":
                result = web_attempt(str(payload.get("action") or ""))
            elif path == "/api/listen":
                action = str(payload.get("action") or "")
                if action == "connect":
                    result = self.lab.connect_operator()
                elif action == "disconnect":
                    result = self.lab.disconnect_operator()
                else:
                    self._json({"customerText": "Request blocked."}, status=400)
                    return
            elif path == "/api/clear":
                result = self.lab.clear_display(str(payload.get("feed") or ""))
            else:
                self.send_error(404)
                return
        except ValueError:
            self._json({"customerText": "Request blocked.", "brokerAccepted": False}, status=400)
            return
        except Exception as exc:
            self._json(
                {
                    "customerText": "The Solace session is not available. Nothing was sent.",
                    "detail": _redact(safe_error(exc), self.lab.config),
                },
                status=503,
            )
            return
        self._json(result)

    def _same_origin(self) -> bool:
        host = self.headers.get("Host", "")
        names = {"127.0.0.1", "localhost"}
        if self.bind_host not in {"0.0.0.0", "::"}:
            names.add(self.bind_host)
        allowed = {f"{name}:{self.port}" for name in names}
        if host not in allowed:
            return False
        origin = self.headers.get("Origin")
        if origin and origin not in {f"http://{name}:{self.port}" for name in names}:
            return False
        return True

    def _missing(self, path: str) -> None:
        if path.startswith("/api/"):
            self._json({"error": "not found"}, status=404)
            return
        self.send_error(404)

    def _redirect(self, target: str) -> None:
        self.close_connection = True
        self.send_response(302)
        self.send_header("Location", target)
        self.send_header("Content-Length", "0")
        self.send_header("Connection", "close")
        self.end_headers()

    def _file(self, name: str, content_type: str) -> None:
        body = (WEB_ROOT / name).read_bytes()
        if name.endswith(".html"):
            body = filter_nav(body.decode("utf-8"), web_role()).encode("utf-8")
        self.close_connection = True
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: dict, status: int = 200) -> None:
        extra = tuple(self.lab.secret_values()) if hasattr(self.lab, "secret_values") else ()
        body = json.dumps(public_payload(payload, self.lab.config, extra)).encode("utf-8")
        self.close_connection = True
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)


def _split_placeholder(split) -> LabConfig:
    """Keeps split passwords available for redaction without selecting the local lab host."""
    publisher = split.publisher
    operator = split.operator
    password = ""
    if publisher is not None and publisher.password:
        password = publisher.password
    elif operator is not None and operator.password:
        password = operator.password
    elif split.semp_password:
        password = split.semp_password
    return LabConfig(
        host="tcp://127.0.0.1:9",
        vpn="default",
        semp_url="http://127.0.0.1:9",
        admin_user="admin",
        admin_password=password or "unused",
        publisher_username=publisher.username if publisher is not None else "publisher",
        publisher_password=publisher.password if publisher is not None else "",
        subscriber_username=operator.username if operator is not None else "operator",
        subscriber_password=operator.password if operator is not None else "",
        allow_remote=False,
    )


def serve() -> None:
    port = web_port()
    role = web_role()
    bind_host = web_bind_host()
    if split_enabled():
        split = load_split_client(role)
        config = _split_placeholder(split)
        lab = LiveLab(config, split=split, role=role)
        try:
            lab.open()
        except Exception as exc:
            lab.broker_connected = False
            lab.last_error = _redact(safe_error(exc), config, tuple(split.secrets()))
        print(split.mode_label())
        print("Split client. provision was not called. No queue, ACL, profile, or bridge change is sent.")
    else:
        config = load_config()
        assert_safe_web_target(config, port)
        lab = LiveLab(config, role=role)
        try:
            provision(config)
            ensure_web_queue(Semp(config), config)
            print(
                f"Browser queue {WEB_QUEUE_NAME} is separate from {QUEUE_NAME}. "
                "This server does not delete either queue and does not acknowledge the quickstart queue."
            )
            lab.open()
        except Exception as exc:
            lab.broker_connected = False
            lab.last_error = _redact(safe_error(exc), config)
        print("Local lab only. Not the cloud bridge. Broker passwords stay on this process.")
    DemoHandler.lab = lab
    DemoHandler.port = port
    DemoHandler.bind_host = bind_host
    server = ThreadingHTTPServer((bind_host, port), DemoHandler)
    shown = bind_host if bind_host not in {"0.0.0.0", "::"} else "127.0.0.1"
    if role in {"all", "publisher"}:
        print(f"Publisher:            http://{shown}:{port}/publisher")
    if role in {"all", "operators"}:
        print(f"Primary Operator:     http://{shown}:{port}/operator")
        print(f"Restricted Operator:  http://{shown}:{port}/restricted-operator")
    if not lab.broker_connected:
        print("Lab broker is not connected. The pages will not invent receipts.")
    try:
        server.serve_forever()
    finally:
        lab.close()
        server.server_close()
