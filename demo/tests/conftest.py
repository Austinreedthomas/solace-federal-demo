"""Keep a developer's demo/.env from changing unit tests."""

import os

import pytest


@pytest.fixture(autouse=True)
def isolate_dotenv(monkeypatch, tmp_path):
    monkeypatch.setenv("SOLACE_DOTENV_PATH", str(tmp_path / "absent.env"))


@pytest.fixture(scope="session", autouse=True)
def remote_shared_clients_stay_on_default():
    """After a Cloud run, the shared clients are still on the default profile and ACL."""
    yield
    if os.environ.get("SOLACE_ALLOW_REMOTE", "").strip().lower() not in {"1", "true", "yes"}:
        return
    from solace_demo.config import load_config
    from solace_demo.provision import assert_shared_clients_unchanged, broker_is_remote

    config = load_config()
    if not broker_is_remote(config):
        return
    assert_shared_clients_unchanged(config)
