"""Load lab settings from the process environment and demo/.env.

demo/.env is parsed as KEY=VALUE text. It is not executed as a shell script.
A value already in the process environment wins over the file.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


class ConfigError(RuntimeError):
    """The lab settings are missing or point somewhere this command refuses."""


@dataclass(frozen=True)
class LabConfig:
    host: str
    vpn: str
    semp_url: str
    admin_user: str
    admin_password: str
    publisher_username: str
    publisher_password: str
    subscriber_username: str
    subscriber_password: str
    allow_remote: bool

    @property
    def semp_base(self) -> str:
        return self.semp_url.rstrip("/")


PASSWORD_KEYS = (
    "SOLACE_ADMIN_PASSWORD",
    "SOLACE_PUBLISHER_PASSWORD",
    "SOLACE_SUBSCRIBER_PASSWORD",
)


def dotenv_path() -> Path:
    override = os.environ.get("SOLACE_DOTENV_PATH", "").strip()
    if override:
        return Path(override)
    return Path(__file__).resolve().parent.parent / ".env"


def parse_dotenv(text: str) -> dict[str, str]:
    """Parse KEY=VALUE lines. Comments and blank lines are ignored."""
    if text.startswith("\ufeff"):
        text = text.lstrip("\ufeff")
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def _file_values() -> dict[str, str]:
    path = dotenv_path()
    if not path.is_file():
        return {}
    return parse_dotenv(path.read_text(encoding="utf-8"))


def _merged(key: str, default: str = "") -> str:
    if key in os.environ:
        return os.environ.get(key, "")
    return _file_values().get(key, default)


def _usable(value: str) -> str:
    text = value.strip()
    if text.startswith("CHANGE_ME"):
        return ""
    return text


def _flag(name: str) -> bool:
    return _merged(name, "").strip().lower() in {"1", "true", "yes"}


def _loopback(url: str) -> bool:
    parsed = urlparse(url if "://" in url else f"tcp://{url}")
    return (parsed.hostname or "").lower() in {"127.0.0.1", "localhost"}


def load_config() -> LabConfig:
    host = _usable(_merged("SOLACE_HOST", "tcp://127.0.0.1:55554"))
    vpn = _usable(_merged("SOLACE_VPN", "default")) or "default"
    semp_url = _usable(_merged("SOLACE_SEMP_URL", "http://127.0.0.1:8080"))
    admin_user = _usable(_merged("SOLACE_ADMIN_USER", "admin")) or "admin"
    admin_password = _usable(_merged("SOLACE_ADMIN_PASSWORD", ""))
    publisher_username = _usable(_merged("SOLACE_PUBLISHER_USERNAME", "ssa-publisher")) or "ssa-publisher"
    publisher_password = _usable(_merged("SOLACE_PUBLISHER_PASSWORD", ""))
    subscriber_username = _usable(_merged("SOLACE_SUBSCRIBER_USERNAME", "ssa-subscriber")) or "ssa-subscriber"
    subscriber_password = _usable(_merged("SOLACE_SUBSCRIBER_PASSWORD", ""))
    allow_remote = _flag("SOLACE_ALLOW_REMOTE")

    missing = [
        name
        for name, value in (
            ("SOLACE_ADMIN_PASSWORD", admin_password),
            ("SOLACE_PUBLISHER_PASSWORD", publisher_password),
            ("SOLACE_SUBSCRIBER_PASSWORD", subscriber_password),
        )
        if not value
    ]
    if missing:
        path = dotenv_path()
        raise ConfigError(
            "Missing "
            + ", ".join(missing)
            + f". Looked at the process environment and {path} (exists={str(path.is_file()).lower()}). "
            "A value already in the environment wins over the file. Do not source the file. "
            "Run python -m solace_demo config-check."
        )
    if not allow_remote and not (_loopback(host) and _loopback(semp_url)):
        raise ConfigError(
            "Refusing SOLACE_HOST or SOLACE_SEMP_URL that is not loopback. "
            "This demo's runnable lab is local. Set SOLACE_ALLOW_REMOTE=1 only "
            "for a broker you have decided to change."
        )
    if vpn != "default" and not allow_remote:
        raise ConfigError(
            "This local lab uses Message VPN 'default'. "
            "A cloud Message VPN name is not asserted and is not configured here."
        )
    return LabConfig(
        host=host,
        vpn=vpn,
        semp_url=semp_url,
        admin_user=admin_user,
        admin_password=admin_password,
        publisher_username=publisher_username,
        publisher_password=publisher_password,
        subscriber_username=subscriber_username,
        subscriber_password=subscriber_password,
        allow_remote=allow_remote,
    )


def chosen_mapping_line(host: str) -> str:
    parsed = urlparse(host if "://" in host else f"tcp://{host}")
    shown = parsed.hostname or host
    if parsed.port:
        shown = f"{shown}:{parsed.port}"
    return (
        f"Chosen host mapping: {shown} -> container port 55555. "
        "Check that host port is free."
    )


def public_report() -> str:
    """Non-secret settings and whether secret keys are non-empty."""
    path = dotenv_path()
    host = _usable(_merged("SOLACE_HOST", "tcp://127.0.0.1:55554"))
    semp_url = _usable(_merged("SOLACE_SEMP_URL", "http://127.0.0.1:8080"))
    vpn = _usable(_merged("SOLACE_VPN", "default")) or "default"
    lines = [
        f"dotenv_path={path}",
        f"dotenv_exists={str(path.is_file()).lower()}",
        f"SOLACE_HOST={host}",
        f"SOLACE_SEMP_URL={semp_url}",
        f"SOLACE_VPN={vpn}",
        f"SOLACE_ALLOW_REMOTE={str(_flag('SOLACE_ALLOW_REMOTE')).lower()}",
        f"loopback={str(_loopback(host) and _loopback(semp_url)).lower()}",
        chosen_mapping_line(host),
    ]
    for key in (
        "SOLACE_ADMIN_USER",
        "SOLACE_PUBLISHER_USERNAME",
        "SOLACE_SUBSCRIBER_USERNAME",
        *PASSWORD_KEYS,
    ):
        present = bool(_usable(_merged(key, "")))
        lines.append(f"{key} set={str(present).lower()}")
    return "\n".join(lines)


def config_check_status() -> int:
    """Return 0 when the lab settings are complete. Do not connect."""
    try:
        load_config()
    except ConfigError:
        return 2
    return 0
