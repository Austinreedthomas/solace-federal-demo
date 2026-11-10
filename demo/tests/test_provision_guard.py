"""Remote brokers keep shared client usernames on their existing profiles."""

from solace_demo.config import LabConfig
from solace_demo.provision import (
    ProvisionError,
    assert_shared_clients_unchanged,
    broker_is_remote,
    ensure_client_username,
    provision,
)
from solace_demo.semp import SempError

import pytest


def _config(host: str, allow_remote: bool = False) -> LabConfig:
    return LabConfig(
        host=host,
        vpn="ground-station",
        semp_url="https://example.invalid:943",
        admin_user="admin",
        admin_password="not-sent",
        publisher_username="solace-cloud-client",
        publisher_password="not-sent",
        subscriber_username="ci-subscriber",
        subscriber_password="not-sent",
        allow_remote=allow_remote,
    )


class RecordingSemp:
    def __init__(self, existing=()):
        self.calls = []
        self.existing = set(existing)

    def request(self, method, path, body=None, ok_exists=False):
        self.calls.append(method)
        if method == "GET":
            name = path.rstrip("/").split("/")[-1]
            if name not in self.existing:
                raise SempError("GET", path, 404, "not found")
            return {
                "data": {
                    "clientUsername": name,
                    "clientProfileName": "default",
                    "aclProfileName": "default",
                }
            }
        return {"data": {}}


def test_remote_provision_does_not_open_semp(monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("SEMP was opened")

    monkeypatch.setattr("solace_demo.provision.Semp", boom)
    lines = provision(_config("tcps://broker.example:55443", allow_remote=True))
    assert any("left as configured" in line for line in lines)


def test_existing_shared_username_is_not_written_on_a_remote_broker():
    config = _config("tcps://broker.example:55443", allow_remote=True)
    semp = RecordingSemp(existing={"solace-cloud-client", "ci-subscriber"})
    for username in ("solace-cloud-client", "ci-subscriber"):
        with pytest.raises(ProvisionError, match="Refusing to modify client username"):
            ensure_client_username(
                semp,
                config,
                username,
                "not-sent",
                "ssa-publisher-acl",
                "ssa-publisher-client",
                allow_remote_update=True,
            )
    assert semp.calls == []


def test_existing_remote_username_needs_the_opt_in_flag(monkeypatch):
    config = _config("tcps://broker.example:55443")
    assert broker_is_remote(config) is True
    semp = RecordingSemp(existing={"perm-demo-user"})
    with pytest.raises(ProvisionError, match="SOLACE_ALLOW_REMOTE_CLIENT_UPDATE"):
        ensure_client_username(
            semp, config, "perm-demo-user", "not-sent", "perm-demo-acl", "perm-demo-client"
        )
    assert semp.calls == ["GET"]
    monkeypatch.setenv("SOLACE_ALLOW_REMOTE_CLIENT_UPDATE", "1")
    ensure_client_username(
        semp, config, "perm-demo-user", "not-sent", "perm-demo-acl", "perm-demo-client"
    )
    assert semp.calls == ["GET", "GET", "PUT"]


def test_loopback_still_replaces_an_existing_client_username():
    config = _config("tcp://127.0.0.1:55555")
    assert broker_is_remote(config) is False
    semp = RecordingSemp(existing={"solace-cloud-client"})
    ensure_client_username(
        semp, config, "solace-cloud-client", "not-sent", "ssa-publisher-acl", "ssa-publisher-client"
    )
    assert semp.calls == ["POST", "PUT"]


def test_shared_client_check_names_a_profile_that_changed():
    config = _config("tcps://broker.example:55443", allow_remote=True)

    class Profiles:
        def request(self, method, path, body=None, ok_exists=False):
            name = path.rstrip("/").split("/")[-1]
            profile = "ssa-publisher-client" if name == "solace-cloud-client" else "default"
            return {"data": {"clientProfileName": profile, "aclProfileName": "default"}}

    from solace_demo import provision as provision_module

    original = provision_module.Semp
    provision_module.Semp = lambda _config: Profiles()
    try:
        with pytest.raises(ProvisionError, match="solace-cloud-client clientProfileName=ssa-publisher-client"):
            assert_shared_clients_unchanged(config)
    finally:
        provision_module.Semp = original
