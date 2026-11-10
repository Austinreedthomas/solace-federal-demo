"""Explicit publisher and operator client sessions.

Used only when SOLACE_SPLIT_CLIENT is set. It does not fall back to
SOLACE_HOST, and it does not create or change queues, ACLs, profiles, or bridges.
Certificate checks stay enabled. A disposable loopback pair is not the cloud service.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from solace.messaging.config.solace_properties import service_properties, transport_layer_properties
from solace.messaging.config.solace_properties.transport_layer_security_properties import CERT_VALIDATED
from solace.messaging.config.transport_security_strategy import TLS

from solace_demo.config import ConfigError, _flag, _merged, _usable
from solace_demo.topics import guaranteed_topic, validate_guaranteed_prefix
from solace_demo.catalog import TOPIC_BOTH


def split_enabled() -> bool:
    return _flag("SOLACE_SPLIT_CLIENT")


@dataclass(frozen=True)
class ClientEndpoint:
    role: str
    host: str
    vpn: str
    username: str
    password: str
    trust_store: str
    passwordless: bool = False

    def client_properties(self) -> dict:
        props = {
            transport_layer_properties.HOST: self.host,
            service_properties.VPN_NAME: self.vpn,
            transport_layer_properties.CONNECTION_RETRIES: 0,
            transport_layer_properties.RECONNECTION_ATTEMPTS: 0,
            transport_layer_properties.CONNECTION_ATTEMPTS_TIMEOUT: 3000,
        }
        if self.host.lower().startswith("tcps://"):
            checked = (
                TLS.create()
                .with_certificate_validation(
                    ignore_expiration=False,
                    validate_server_name=True,
                    trust_store_file_path=self.trust_store,
                )
                .security_configuration
            )
            props.update(checked)
            if props.get(CERT_VALIDATED) is not True:
                raise ConfigError("Certificate validation did not stay enabled.")
        return props


@dataclass(frozen=True)
class SplitClient:
    publisher: Optional[ClientEndpoint]
    operator: Optional[ClientEndpoint]
    operator_queue: str
    semp_url: str
    semp_username: str
    semp_password: str
    guaranteed_prefix: str = ""

    @property
    def management_changes(self) -> bool:
        return False

    @property
    def validated_cloud_path(self) -> bool:
        return False

    def secrets(self) -> list:
        values = []
        if self.publisher is not None:
            values.append(self.publisher.password)
        if self.operator is not None:
            values.append(self.operator.password)
        values.append(self.semp_password)
        return [item for item in values if item]

    def mode_label(self) -> str:
        if self.publisher is None and self.operator is not None:
            operator = _host_port(self.operator.host)
            return f"Operator {operator} VPN {self.operator.vpn}."
        if self.operator is None and self.publisher is not None:
            publisher = _host_port(self.publisher.host)
            return f"Publisher {publisher} VPN {self.publisher.vpn}."
        publisher = _host_port(self.publisher.host)
        operator = _host_port(self.operator.host)
        auth = ""
        if self.operator.passwordless:
            auth = " Operator authentication: none. Not an ACL or identity proof."
        if _loopback(self.publisher.host) and _loopback(self.operator.host):
            return (
                f"Disposable two-endpoint test. Publisher {publisher} VPN {self.publisher.vpn}. "
                f"Operator {operator} VPN {self.operator.vpn}.{auth} "
                "Not the cloud service and not a completed Mac proof."
            )
        return (
            f"Split client. Publisher {publisher} VPN {self.publisher.vpn}. "
            f"Operator {operator} VPN {self.operator.vpn}.{auth} "
            "Not a completed cloud-to-Mac proof. This process does not change either broker."
        )

    def guaranteed_note(self) -> str:
        if self.operator is None:
            if not self.guaranteed_prefix:
                return "Guaranteed alerts stay off until SOLACE_GUARANTEED_TOPIC_PREFIX is set."
            topic = guaranteed_topic(TOPIC_BOTH, self.guaranteed_prefix)
            return f"Topic {topic}. A broker ACK means the broker accepted it."
        if not self.operator_queue:
            return (
                "Guaranteed alerts stay off until an existing operator queue name is configured. "
                "Direct alerts can still be sent."
            )
        if not self.guaranteed_prefix:
            return (
                "Guaranteed alerts stay off until SOLACE_GUARANTEED_TOPIC_PREFIX is set outside ssa/. "
                f"Queue {self.operator_queue} is set. Direct alerts stay on ssa/unclass/."
            )
        topic = guaranteed_topic(TOPIC_BOTH, self.guaranteed_prefix)
        return (
            f"Topic {topic}. "
            f"Queue {self.operator_queue} holds it while this console is offline. "
            "A broker ACK means the broker accepted it. This console shows the alert when it arrives."
        )

    def queue_count(self) -> Optional[int]:
        """Read-only message list. No management write is sent."""
        if self.operator is None or not self.operator_queue or not self.semp_url:
            return None
        vpn = quote(self.operator.vpn, safe="")
        queue = quote(self.operator_queue, safe="")
        target = (
            self.semp_url.rstrip("/")
            + f"/SEMP/v2/monitor/msgVpns/{vpn}/queues/{queue}/msgs?count=100"
        )
        req = Request(target, method="GET")
        token = base64.b64encode(f"{self.semp_username}:{self.semp_password}".encode("utf-8")).decode("ascii")
        req.add_header("Authorization", "Basic " + token)
        try:
            with urlopen(req, timeout=1.0) as response:
                raw = response.read()
        except Exception:
            return None
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return None
        from solace_demo.live import waiting_message_count

        return waiting_message_count(payload)


def load_split_client(role: str = "all") -> SplitClient:
    if not split_enabled():
        raise ConfigError("SOLACE_SPLIT_CLIENT is not set.")
    if role not in {"all", "publisher", "operators"}:
        raise ConfigError("SOLACE_WEB_ROLE must be all, publisher, or operators.")
    if _flag("SOLACE_TLS_INSECURE") or _usable(_merged("SOLACE_TLS_CERT_VALIDATED", "")).lower() in {"0", "false", "no"}:
        raise ConfigError("Refusing to disable broker certificate checks.")
    publisher = None if role == "operators" else _endpoint("publisher", "SOLACE_PUBLISHER", allow_passwordless=False)
    operator = None if role == "publisher" else _endpoint("operator", "SOLACE_OPERATOR", allow_passwordless=True)
    if publisher is not None and operator is not None and _endpoint_key(publisher.host) == _endpoint_key(operator.host):
        raise ConfigError("The publisher host and the operator host must be different.")
    queue = _usable(_merged("SOLACE_OPERATOR_QUEUE", ""))
    if queue and ("/" in queue or queue.startswith(".")):
        raise ConfigError("SOLACE_OPERATOR_QUEUE is not a single queue name.")
    raw_prefix = _usable(_merged("SOLACE_GUARANTEED_TOPIC_PREFIX", ""))
    prefix = validate_guaranteed_prefix(raw_prefix) if raw_prefix else ""
    if role == "publisher":
        queue = ""
        semp_url = ""
        semp_user = ""
        semp_password = ""
    else:
        semp_url = _usable(_merged("SOLACE_OPERATOR_SEMP_URL", ""))
        semp_user = _usable(_merged("SOLACE_OPERATOR_SEMP_USERNAME", ""))
        semp_password = _usable(_merged("SOLACE_OPERATOR_SEMP_PASSWORD", ""))
    if semp_url and not (semp_user and semp_password):
        raise ConfigError("SOLACE_OPERATOR_SEMP_URL needs SOLACE_OPERATOR_SEMP_USERNAME and SOLACE_OPERATOR_SEMP_PASSWORD.")
    if semp_url:
        _require_bare_url("SOLACE_OPERATOR_SEMP_URL", semp_url, {"http", "https"}, {"http"})
    return SplitClient(publisher, operator, queue, semp_url, semp_user, semp_password, prefix)


def _endpoint(role: str, prefix: str, allow_passwordless: bool) -> ClientEndpoint:
    host = _usable(_merged(prefix + "_HOST", ""))
    vpn = _usable(_merged(prefix + "_VPN", ""))
    username = _usable(_merged(prefix + "_USERNAME", ""))
    password = _usable(_merged(prefix + "_PASSWORD", ""))
    trust = _usable(_merged(prefix + "_TRUST_STORE", ""))
    auth = _usable(_merged(prefix + "_AUTH", "")).lower()
    if auth in {"no-auth", "noauth"}:
        auth = "none"
    passwordless = auth == "none"
    if passwordless and not allow_passwordless:
        raise ConfigError(prefix + "_AUTH=none is not allowed. This endpoint still requires a password.")
    if auth not in {"", "password", "none"}:
        raise ConfigError(prefix + "_AUTH must be password or none.")
    missing = [
        name
        for name, value in (
            (prefix + "_HOST", host),
            (prefix + "_VPN", vpn),
            (prefix + "_USERNAME", username),
        )
        if not value
    ]
    if not passwordless and not password:
        missing.append(prefix + "_PASSWORD")
    if passwordless and password:
        raise ConfigError(prefix + "_AUTH=none does not take a password. Remove " + prefix + "_PASSWORD.")
    if missing:
        raise ConfigError("Missing " + ", ".join(missing) + ".")
    _require_bare_url(prefix + "_HOST", host, {"tcp", "tcps"}, {"tcp"})
    if passwordless and (urlparse(host).scheme != "tcp" or not _loopback(host)):
        raise ConfigError(prefix + "_AUTH=none is only allowed for a loopback tcp:// endpoint.")
    if urlparse(host).scheme == "tcps":
        if not trust or not Path(trust).is_dir():
            raise ConfigError(prefix + "_TRUST_STORE must be a directory of trusted certificates.")
    elif trust:
        raise ConfigError(prefix + "_TRUST_STORE is only used with tcps://.")
    return ClientEndpoint(role, host, vpn, username, "" if passwordless else password, trust, passwordless)


def _require_bare_url(label: str, url: str, schemes: set, plaintext: set) -> None:
    """Reject userinfo, path, query, and cleartext to a remote host.

    The error names the setting only. It does not repeat the URL.
    """
    parsed = urlparse(url)
    tail = url.split("://", 1)[-1]
    if parsed.username or parsed.password or "@" in tail:
        raise ConfigError(label + " must not include a username or password.")
    if parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise ConfigError(label + " must not include a path, query, or fragment.")
    if parsed.scheme not in schemes or not parsed.hostname or not parsed.port:
        raise ConfigError(label + " must include a scheme, host, and port.")
    if parsed.scheme in plaintext and not _loopback_host(parsed.hostname):
        raise ConfigError(
            label + " refuses cleartext outside 127.0.0.1, localhost, or ::1. Use tcps:// for SMF or https:// for management."
        )


def _loopback_host(hostname: str) -> bool:
    return hostname.lower() in {"127.0.0.1", "localhost", "::1"}


def _endpoint_key(host: str) -> tuple:
    parsed = urlparse(host)
    return (parsed.scheme.lower(), (parsed.hostname or "").lower(), parsed.port)


def _loopback(host: str) -> bool:
    return _loopback_host(urlparse(host).hostname or "")


# Public Solace Cloud messaging DNS suffix. A service id is not included.
_CLOUD_DNS_SUFFIX = "messaging" + "." + "solace" + "." + "cloud"


def _hostname(host: str) -> str:
    parsed = urlparse(host if "://" in host else f"tcp://{host}")
    name = (parsed.hostname or "").lower().rstrip(".")
    return name


def is_solace_cloud_host(host: str) -> bool:
    """True only for the public Cloud messaging suffix, on a label boundary."""
    name = _hostname(host)
    suffix = _CLOUD_DNS_SUFFIX
    return name == suffix or name.endswith("." + suffix)


def demo_broker_label(host: str) -> str:
    """A demo-facing broker name. The host is not included."""
    parsed = urlparse(host if "://" in host else f"tcp://{host}")
    scheme = (parsed.scheme or "").lower()
    if scheme == "tcps" and is_solace_cloud_host(host):
        return "my Solace Cloud broker"
    if _loopback_host(parsed.hostname or ""):
        return "my local Solace broker"
    return "a remote Solace broker"


def _configured_display_label(raw: str) -> str:
    text = (raw or "").strip()
    if not text or len(text) > 60:
        return ""
    if any((ch != " " and ch.isspace()) or ord(ch) < 32 or ord(ch) == 127 for ch in text):
        return ""
    return text


def display_broker_label(host: str, configured: str = "") -> str:
    """Compact page name. A configured label wins. The host is not included."""
    chosen = _configured_display_label(configured)
    if chosen:
        return chosen
    parsed = urlparse(host if "://" in host else f"tcp://{host}")
    scheme = (parsed.scheme or "").lower()
    if scheme == "tcps" and is_solace_cloud_host(host):
        return "Solace Cloud"
    return "Solace broker"


def peer_name(host: str, role: str) -> str:
    """Short name for one configured session. No private service id is built in.

    Only a publisher on the public Cloud messaging suffix is called Solace Cloud.
    Any other TLS host or address stays a remote Solace broker. A loopback
    operator is the local Solace broker. Loopback publishers are the local lab.
    """
    parsed = urlparse(host if "://" in host else f"tcp://{host}")
    scheme = (parsed.scheme or "").lower()
    loopback = _loopback_host(parsed.hostname or "")
    if role == "publisher" and scheme == "tcps" and is_solace_cloud_host(host):
        return "Solace Cloud"
    if loopback and role == "operator":
        return "local Solace broker"
    if loopback:
        return "local lab broker"
    return "remote Solace broker"


def link_status(name: str, connected: bool) -> str:
    if connected:
        return f"Connected to {name}"
    return f"Not connected. Configured target: {name}"


def operator_headline(name: str, connected: bool, listening: bool, failed: bool) -> str:
    """What this console's own Solace receiver is doing. Not a broker health light."""
    if connected and listening and not failed:
        return f"Receiving from {name}"
    if connected:
        return f"Not receiving. The Solace session to {name} is still up."
    return f"Not receiving. Configured target: {name}"


def path_note(split_mode: bool, publisher_name: str, operator_name: str, both_loopback: bool = False) -> str:
    if not split_mode:
        return "Both windows use this one local lab broker."
    if both_loopback:
        return (
            f"Disposable local endpoints. Publisher is the {publisher_name}. "
            f"Operator is the {operator_name}."
        )
    return (
        f"Configured sessions. Publisher is {publisher_name}. "
        f"Operator is the {operator_name}."
    )


def _host_port(host: str) -> str:
    parsed = urlparse(host)
    return f"{parsed.hostname}:{parsed.port}"

