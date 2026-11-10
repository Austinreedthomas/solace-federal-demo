"""Set the lab container admin password from demo/.env without printing it.

Solace applies username_admin_password only when the storage volume is first
created. A later `docker compose up -d` does not change the stored password.
"""

from __future__ import annotations

import base64
import os
import select
import shutil
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from solace_demo.config import ConfigError, LabConfig

LAB_CONTAINER = "solace-ssa-demo"
CLI = "/usr/sw/loads/currentload/bin/cli"
# Solace CLI passwords exclude these characters. See Configuring Internal CLI User Accounts.
_FORBIDDEN = set(':()";\'<>,`\\*&|')


def assert_password_acceptable(password: str) -> None:
    if any(char.isspace() or char in _FORBIDDEN for char in password):
        raise ConfigError(
            "SOLACE_ADMIN_PASSWORD contains a space or a character the Solace CLI rejects. "
            "Choose another lab-only alphanumeric password in demo/.env. The value was not printed."
        )


def _redact(text: str, password: str) -> str:
    return text.replace(password, "<redacted>")


def _semp_status(config: LabConfig) -> int | str:
    token = base64.b64encode(f"{config.admin_user}:{config.admin_password}".encode()).decode()
    request = Request(config.semp_base + "/SEMP/v2/config/about")
    request.add_header("Authorization", "Basic " + token)
    try:
        with urlopen(request, timeout=5) as response:
            return response.status
    except HTTPError as exc:
        return exc.code
    except URLError as exc:
        return type(exc.reason).__name__ if getattr(exc, "reason", None) else "URLError"


def sync_admin_password(config: LabConfig, container: str = LAB_CONTAINER) -> list[str]:
    """Change admin inside one named container. Does not delete storage."""
    if container != LAB_CONTAINER and os.environ.get("SOLACE_SYNC_ALLOW_TEST_CONTAINER") != "1":
        raise ConfigError(f"Refusing to touch container {container}. Only {LAB_CONTAINER} is allowed.")
    assert_password_acceptable(config.admin_password)
    docker = shutil.which("docker")
    if not docker:
        raise ConfigError("docker was not found on PATH.")
    import pty

    master, slave = pty.openpty()
    process = subprocess.Popen(
        [docker, "exec", "-it", container, CLI, "-A"],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        close_fds=True,
    )
    os.close(slave)
    captured = b""

    def drain(seconds: float) -> None:
        nonlocal captured
        end = time.time() + seconds
        while time.time() < end:
            ready, _, _ = select.select([master], [], [], 0.2)
            if master not in ready:
                continue
            try:
                chunk = os.read(master, 4096)
            except OSError:
                break
            if not chunk:
                break
            captured += chunk

    try:
        drain(2)
        command = (
            "enable\rconfigure\rusername admin\r"
            f"change-password {config.admin_password}\r"
            "end\rexit\r"
        )
        os.write(master, command.encode())
        drain(4)
    finally:
        os.close(master)
        process.wait(timeout=15)
    session = _redact(captured.decode("utf-8", "replace"), config.admin_password)
    if "configure/username" not in session or process.returncode not in (0, None):
        snippet = " ".join(session.split())[:240]
        raise ConfigError(
            f"The admin CLI session on {container} did not reach username configuration. "
            f"Storage was not deleted. Output: {snippet}"
        )
    status = _semp_status(config)
    if status != 200:
        raise ConfigError(
            f"SEMP /SEMP/v2/config/about returned {status} after the password update. "
            "Storage was not deleted."
        )
    return [
        f"Updated the admin password inside container {container}.",
        "SEMP /SEMP/v2/config/about now returns 200 with the password from demo/.env.",
        "No volume was deleted.",
    ]
