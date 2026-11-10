"""SEMP v2 calls for dev init only. Request bodies with passwords are not logged."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from solace_demo.config import LabConfig


class SempError(RuntimeError):
    def __init__(self, method: str, path: str, status: int, description: str):
        super().__init__(f"SEMP {method} {path} -> {status}: {description}")
        self.method = method
        self.path = path
        self.status = status
        self.description = description


def _description(body: bytes) -> str:
    try:
        payload = json.loads(body.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return "unreadable SEMP response"
    error = (payload.get("meta") or {}).get("error") or {}
    text = error.get("description") or error.get("status") or "SEMP error"
    return str(text)[:500]


class Semp:
    def __init__(self, config: LabConfig, timeout: float = 10.0):
        self._config = config
        self._timeout = timeout

    def request(self, method: str, path: str, body: dict | None = None, ok_exists: bool = False) -> dict:
        url = self._config.semp_base + path
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        # admin credentials stay in the Authorization header and are not printed.
        token = _basic(self._config.admin_user, self._config.admin_password)
        req.add_header("Authorization", "Basic " + token)
        try:
            with urlopen(req, timeout=self._timeout) as response:
                raw = response.read()
                status = response.status
        except HTTPError as exc:
            raw = exc.read()
            status = exc.code
            description = _description(raw)
            if ok_exists and status == 400 and "already exists" in description.lower():
                return {"meta": {"responseCode": status}, "alreadyExists": True}
            raise SempError(method, path, status, description) from None
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))


def _basic(user: str, password: str) -> str:
    import base64

    return base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")


def acl_counters(payload: Any) -> dict[str, Any]:
    """Pull monitor fields whose names mention acl or denied. Ignore the rest."""
    found: dict[str, Any] = {}

    def walk(node: Any, prefix: str = "") -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                path = f"{prefix}.{key}" if prefix else str(key)
                if isinstance(value, (dict, list)):
                    walk(value, path)
                elif any(word in key.lower() for word in ("acl", "denied", "discard")):
                    found[path] = value
        elif isinstance(node, list):
            for index, item in enumerate(node[:5]):
                walk(item, f"{prefix}[{index}]")

    walk(payload)
    return found
