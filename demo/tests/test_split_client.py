"""Guards for the opt-in publisher and operator client sessions."""

from __future__ import annotations

from solace.messaging.config.solace_properties.transport_layer_security_properties import CERT_VALIDATED

import pytest

from solace_demo.config import ConfigError
from solace_demo.split_client import load_split_client


def _clear(monkeypatch):
    for name in (
        "SOLACE_SPLIT_CLIENT",
        "SOLACE_TLS_INSECURE",
        "SOLACE_TLS_CERT_VALIDATED",
        "SOLACE_PUBLISHER_HOST",
        "SOLACE_PUBLISHER_VPN",
        "SOLACE_PUBLISHER_USERNAME",
        "SOLACE_PUBLISHER_PASSWORD",
        "SOLACE_PUBLISHER_TRUST_STORE",
        "SOLACE_OPERATOR_HOST",
        "SOLACE_OPERATOR_VPN",
        "SOLACE_OPERATOR_USERNAME",
        "SOLACE_OPERATOR_PASSWORD",
        "SOLACE_OPERATOR_TRUST_STORE",
        "SOLACE_OPERATOR_QUEUE",
        "SOLACE_OPERATOR_SEMP_URL",
        "SOLACE_OPERATOR_SEMP_USERNAME",
        "SOLACE_OPERATOR_SEMP_PASSWORD",
    ):
        monkeypatch.delenv(name, raising=False)


def _base(monkeypatch, publisher="tcp://127.0.0.1:16655", operator="tcp://127.0.0.1:16755"):
    _clear(monkeypatch)
    monkeypatch.setenv("SOLACE_SPLIT_CLIENT", "1")
    monkeypatch.setenv("SOLACE_PUBLISHER_HOST", publisher)
    monkeypatch.setenv("SOLACE_PUBLISHER_VPN", "pub-vpn")
    monkeypatch.setenv("SOLACE_PUBLISHER_USERNAME", "pub-user")
    monkeypatch.setenv("SOLACE_PUBLISHER_PASSWORD", "pub-secret")
    monkeypatch.setenv("SOLACE_OPERATOR_HOST", operator)
    monkeypatch.setenv("SOLACE_OPERATOR_VPN", "op-vpn")
    monkeypatch.setenv("SOLACE_OPERATOR_USERNAME", "op-user")
    monkeypatch.setenv("SOLACE_OPERATOR_PASSWORD", "op-secret")


def test_connection_labels_follow_the_configured_endpoint(monkeypatch, tmp_path):
    from solace_demo.config import LabConfig
    from solace_demo.live import LiveLab
    from solace_demo.split_client import link_status, operator_headline, path_note, peer_name

    assert peer_name("tcp://127.0.0.1:15555", "publisher") == "local lab broker"
    assert peer_name("tcp://127.0.0.1:55554", "operator") == "local Solace broker"
    assert peer_name("tcps://203.0.113.10:55443", "publisher") == "remote Solace broker"
    assert peer_name("tcps://broker.example.com:55443", "publisher") == "remote Solace broker"
    cloud = "tcps://region.messaging.solace.cloud:55443"
    assert peer_name(cloud, "publisher") == "Solace Cloud"
    assert peer_name("tcps://messaging.solace.cloud:55443", "publisher") == "Solace Cloud"
    assert peer_name("tcps://Region.Messaging.Solace.Cloud.:55443", "publisher") == "Solace Cloud"
    for deceptive in (
        "tcps://evilmessaging.solace.cloud:55443",
        "tcps://messaging.solace.cloud.evil.example:55443",
        "tcps://not.messaging.solace.cloud.attacker.com:55443",
        "tcps://solace.cloud:55443",
        "tcp://region.messaging.solace.cloud:55443",
    ):
        assert peer_name(deceptive, "publisher") == "remote Solace broker", deceptive
    assert link_status("Solace Cloud", False).startswith("Not connected")
    assert "Connected to" not in link_status("Solace Cloud", False)
    assert link_status("local Solace broker", True) == "Connected to local Solace broker"
    assert operator_headline("local Solace broker", True, True, False) == "Receiving from local Solace broker"
    assert "Connected" not in operator_headline("local Solace broker", True, False, False)
    assert "still up" in operator_headline("local Solace broker", True, False, True)
    assert operator_headline("local lab broker", False, False, True).startswith("Not receiving.")
    cloud_path = path_note(True, "Solace Cloud", "local Solace broker", both_loopback=False)
    assert "Publisher is Solace Cloud" in cloud_path
    assert "Not Kafka" not in cloud_path
    assert "Disposable" not in cloud_path
    assert "bridge" not in cloud_path.lower()
    remote_path = path_note(True, "remote Solace broker", "local Solace broker", both_loopback=False)
    assert remote_path.startswith("Configured sessions.")
    assert "Disposable" not in remote_path
    assert "Not Solace Cloud" not in remote_path
    pair = path_note(True, "local lab broker", "local Solace broker", both_loopback=True)
    assert pair.startswith("Disposable local endpoints.")
    local_path = path_note(False, "local lab broker", "local lab broker")
    assert "one local lab broker" in local_path
    assert "Not Solace Cloud" not in local_path
    assert "Not Kafka" not in local_path
    lab = LiveLab(
        LabConfig(
            host="tcp://127.0.0.1:15555",
            vpn="default",
            semp_url="http://127.0.0.1:18080",
            admin_user="admin",
            admin_password="local-only",
            publisher_username="ssa-publisher",
            publisher_password="local-only",
            subscriber_username="ssa-subscriber",
            subscriber_password="local-only",
            allow_remote=False,
        )
    )
    local = lab.snapshot()
    assert local["publisherName"] == "local lab broker"
    assert local["operatorStatus"].startswith("Not receiving.")
    assert "Connected" not in local["operatorStatus"]
    assert "Solace Cloud" not in local["publisherStatus"]
    assert local["operatorConnected"] is False
    assert local["queueConfigured"] is True
    trust = tmp_path / "trust"
    trust.mkdir()
    _base(monkeypatch, publisher="tcps://203.0.113.10:55443", operator="tcp://127.0.0.1:55554")
    monkeypatch.setenv("SOLACE_PUBLISHER_TRUST_STORE", str(trust))
    monkeypatch.delenv("SOLACE_OPERATOR_QUEUE", raising=False)
    split = load_split_client()
    remote = LiveLab(
        LabConfig(
            host="tcp://127.0.0.1:9",
            vpn="default",
            semp_url="http://127.0.0.1:9",
            admin_user="admin",
            admin_password="local-only",
            publisher_username="pub-user",
            publisher_password="pub-secret",
            subscriber_username="op-user",
            subscriber_password="op-secret",
            allow_remote=False,
        ),
        split=split,
    ).snapshot()
    assert remote["publisherName"] == "remote Solace broker"
    assert remote["publisherStatus"].startswith("Not connected")
    assert remote["operatorName"] == "local Solace broker"
    assert remote["queueConfigured"] is False
    assert remote["connectDisabled"] is False
    assert remote["disconnectDisabled"] is True
    assert "Disposable" not in remote["pathNote"]
    assert "Not Solace Cloud" not in remote["pathNote"]
    assert "203.0.113.10:55443" in remote["publisherDetail"]
    assert "pub-secret" not in str(remote["publisherDetail"]) + remote["publisherStatus"] + remote["pathNote"]
    monkeypatch.setenv("SOLACE_OPERATOR_AUTH", "none")
    monkeypatch.delenv("SOLACE_OPERATOR_PASSWORD", raising=False)
    passwordless = load_split_client()
    noted = LiveLab(
        LabConfig(
            host="tcp://127.0.0.1:9",
            vpn="default",
            semp_url="http://127.0.0.1:9",
            admin_user="admin",
            admin_password="local-only",
            publisher_username="pub-user",
            publisher_password="pub-secret",
            subscriber_username="op-user",
            subscriber_password="",
            allow_remote=False,
        ),
        split=passwordless,
    ).snapshot()
    assert noted["authNote"] == "Operator authentication: none. Not an ACL or identity proof."
    assert "ACL" in passwordless.mode_label()
    monkeypatch.setenv("SOLACE_PUBLISHER_HOST", "tcps://region.messaging.solace.cloud:55443")
    cloud = load_split_client()
    cloud_state = LiveLab(
        LabConfig(
            host="tcp://127.0.0.1:9",
            vpn="default",
            semp_url="http://127.0.0.1:9",
            admin_user="admin",
            admin_password="local-only",
            publisher_username="pub-user",
            publisher_password="pub-secret",
            subscriber_username="op-user",
            subscriber_password="",
            allow_remote=False,
        ),
        split=cloud,
    ).snapshot()
    assert cloud_state["publisherName"] == "Solace Cloud"
    assert cloud_state["publisherStatus"].startswith("Not connected")
    assert cloud_state["operatorName"] == "local Solace broker"
    assert cloud_state["queueConfigured"] is False
    assert "Not an ACL or identity proof" in cloud_state["authNote"]
    assert "Disposable" not in cloud_state["pathNote"]
    assert "bridge" not in cloud_state["pathNote"].lower()
    assert cloud_state["operatorStatus"].startswith("Not receiving.")
    assert "Connected" not in cloud_state["operatorStatus"]
    assert "lab broker" not in cloud_state["pathNote"]
    down = LiveLab(
        LabConfig(
            host="tcp://127.0.0.1:9",
            vpn="default",
            semp_url="http://127.0.0.1:9",
            admin_user="admin",
            admin_password="local-only",
            publisher_username="pub-user",
            publisher_password="pub-secret",
            subscriber_username="op-user",
            subscriber_password="",
            allow_remote=False,
        ),
        split=cloud,
    )._down_text()
    assert "lab broker" not in down
    assert "Solace Cloud" in down
    assert "local Solace broker" in down
    assert cloud_state["connectDisabled"] is False
    assert cloud_state["disconnectDisabled"] is True


def test_split_off_does_not_adopt_publisher_host(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("SOLACE_PUBLISHER_HOST", "tcps://203.0.113.10:55443")
    monkeypatch.setenv("SOLACE_HOST", "tcp://127.0.0.1:15555")
    from solace_demo.endpoints import future_endpoints

    reported = future_endpoints()
    assert reported["usedByWebServer"] is False
    assert reported["publisherHost"] == ""
    assert reported["validated"] is False


def test_split_requires_both_endpoints_and_does_not_echo_secrets(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("SOLACE_SPLIT_CLIENT", "1")
    monkeypatch.setenv("SOLACE_PUBLISHER_PASSWORD", "pub-secret")
    with pytest.raises(ConfigError) as raised:
        load_split_client()
    text = str(raised.value)
    assert "SOLACE_PUBLISHER_HOST" in text
    assert "pub-secret" not in text


def test_cleartext_and_url_secrets_are_refused(monkeypatch, tmp_path):
    _base(monkeypatch, publisher="tcp://203.0.113.10:55555")
    with pytest.raises(ConfigError) as raised:
        load_split_client()
    assert "cleartext" in str(raised.value)
    assert "203.0.113.10" not in str(raised.value)
    _base(monkeypatch, publisher="tcp://alice:super-secret@127.0.0.1:16655")
    with pytest.raises(ConfigError) as raised:
        load_split_client()
    assert "super-secret" not in str(raised.value)
    assert "username or password" in str(raised.value)
    _base(monkeypatch)
    monkeypatch.setenv("SOLACE_OPERATOR_SEMP_URL", "http://bob:semp-secret@203.0.113.8:8080/admin?token=semp-secret")
    monkeypatch.setenv("SOLACE_OPERATOR_SEMP_USERNAME", "reader")
    monkeypatch.setenv("SOLACE_OPERATOR_SEMP_PASSWORD", "reader-secret")
    with pytest.raises(ConfigError) as raised:
        load_split_client()
    assert "semp-secret" not in str(raised.value)
    assert "reader-secret" not in str(raised.value)
    _base(monkeypatch)
    monkeypatch.setenv("SOLACE_OPERATOR_SEMP_URL", "http://203.0.113.8:8080")
    monkeypatch.setenv("SOLACE_OPERATOR_SEMP_USERNAME", "reader")
    monkeypatch.setenv("SOLACE_OPERATOR_SEMP_PASSWORD", "reader-secret")
    with pytest.raises(ConfigError) as raised:
        load_split_client()
    assert "cleartext" in str(raised.value)
    assert "203.0.113.8" not in str(raised.value)
    trust = tmp_path / "trust"
    trust.mkdir()
    _base(monkeypatch, publisher="tcps://203.0.113.10:55443")
    monkeypatch.setenv("SOLACE_PUBLISHER_TRUST_STORE", str(trust))
    monkeypatch.setenv("SOLACE_OPERATOR_SEMP_URL", "https://127.0.0.1:9443")
    monkeypatch.setenv("SOLACE_OPERATOR_SEMP_USERNAME", "reader")
    monkeypatch.setenv("SOLACE_OPERATOR_SEMP_PASSWORD", "reader-secret")
    split = load_split_client()
    assert split.semp_url == "https://127.0.0.1:9443"
    from pathlib import Path
    source = Path(__file__).resolve().parents[1].joinpath("solace_demo", "split_client.py").read_text(encoding="utf-8")
    assert "without_certificate_validation" not in source
    assert "unverified" not in source


def test_split_refuses_one_host_and_disabled_certificate_checks(monkeypatch, tmp_path):
    _base(monkeypatch, operator="tcp://127.0.0.1:16655")
    with pytest.raises(ConfigError) as raised:
        load_split_client()
    assert "different" in str(raised.value)
    _base(monkeypatch, publisher="tcps://203.0.113.10:55443")
    monkeypatch.setenv("SOLACE_TLS_INSECURE", "1")
    with pytest.raises(ConfigError) as raised:
        load_split_client()
    assert "certificate" in str(raised.value).lower()
    assert "pub-secret" not in str(raised.value)
    monkeypatch.delenv("SOLACE_TLS_INSECURE", raising=False)
    with pytest.raises(ConfigError) as raised:
        load_split_client()
    assert "TRUST_STORE" in str(raised.value)
    trust = tmp_path / "trust"
    trust.mkdir()
    monkeypatch.setenv("SOLACE_PUBLISHER_TRUST_STORE", str(trust))
    split = load_split_client()
    props = split.publisher.client_properties()
    assert props["solace.messaging.transport.host"] == "tcps://203.0.113.10:55443"
    assert props[CERT_VALIDATED] is True
    assert props["solace.messaging.tls.cert-validate-servername"] is True
    assert props["solace.messaging.tls.cert-reject-expired"] is True
    assert split.management_changes is False
    assert split.validated_cloud_path is False
    assert "Disposable" not in split.mode_label()
    assert "Not a completed cloud-to-Mac proof" in split.mode_label()
    assert "pub-secret" not in split.mode_label()


def test_passwordless_operator_is_loopback_only_and_not_a_fallback(monkeypatch):
    _base(monkeypatch)
    monkeypatch.delenv("SOLACE_OPERATOR_PASSWORD", raising=False)
    monkeypatch.setenv("SOLACE_SUBSCRIBER_PASSWORD", "borrowed-secret")
    monkeypatch.setenv("SOLACE_PUBLISHER_PASSWORD", "pub-secret")
    with pytest.raises(ConfigError) as raised:
        load_split_client()
    assert "SOLACE_OPERATOR_PASSWORD" in str(raised.value)
    assert "borrowed-secret" not in str(raised.value)
    monkeypatch.setenv("SOLACE_OPERATOR_AUTH", "none")
    split = load_split_client()
    assert split.operator.passwordless is True
    assert split.operator.password == ""
    assert split.publisher.password == "pub-secret"
    assert "borrowed-secret" not in split.secrets()
    assert "Not an ACL or identity proof" in split.mode_label()
    assert "pub-secret" not in split.mode_label()
    monkeypatch.setenv("SOLACE_OPERATOR_PASSWORD", "op-secret")
    with pytest.raises(ConfigError) as raised:
        load_split_client()
    assert "does not take a password" in str(raised.value)
    assert "op-secret" not in str(raised.value)
    monkeypatch.delenv("SOLACE_OPERATOR_PASSWORD", raising=False)
    monkeypatch.setenv("SOLACE_PUBLISHER_AUTH", "none")
    with pytest.raises(ConfigError) as raised:
        load_split_client()
    assert "SOLACE_PUBLISHER_AUTH" in str(raised.value)
    monkeypatch.delenv("SOLACE_PUBLISHER_AUTH", raising=False)
    monkeypatch.setenv("SOLACE_OPERATOR_HOST", "tcps://203.0.113.10:55443")
    with pytest.raises(ConfigError) as raised:
        load_split_client()
    text = str(raised.value)
    assert "loopback" in text
    assert "203.0.113.10" not in text
    assert "pub-secret" not in text


def test_guaranteed_prefix_is_opt_in_and_rejects_the_direct_tree(monkeypatch):
    _base(monkeypatch)
    monkeypatch.setenv("SOLACE_OPERATOR_QUEUE", "queue-local-operator-guaranteed")
    split = load_split_client()
    assert split.guaranteed_prefix == ""
    assert "stay off until SOLACE_GUARANTEED_TOPIC_PREFIX" in split.guaranteed_note()
    assert "ssa/unclass" in split.guaranteed_note()
    monkeypatch.setenv("SOLACE_GUARANTEED_TOPIC_PREFIX", "ssa/unclass")
    with pytest.raises(ConfigError) as raised:
        load_split_client()
    assert "ssa/" in str(raised.value) or "ssa" in str(raised.value)
    assert "pub-secret" not in str(raised.value)
    monkeypatch.setenv("SOLACE_GUARANTEED_TOPIC_PREFIX", "ssa-guaranteed/unclass")
    ready = load_split_client()
    assert ready.guaranteed_prefix == "ssa-guaranteed/unclass"
    note = ready.guaranteed_note()
    assert "ssa-guaranteed/unclass/ground1/launch/25544/alert" in note
    assert "queue-local-operator-guaranteed" in note
    assert note.endswith(".")
    assert "holds it while this console is offline" in note
    assert "broker accepted it" in note
    assert "not that this console" not in note
    from solace_demo.config import LabConfig
    from solace_demo.live import LiveLab

    lab = LiveLab(
        LabConfig(
            host="tcp://127.0.0.1:9",
            vpn="default",
            semp_url="http://127.0.0.1:9",
            admin_user="admin",
            admin_password="local-only",
            publisher_username="pub-user",
            publisher_password="pub-secret",
            subscriber_username="op-user",
            subscriber_password="op-secret",
            allow_remote=False,
        ),
        split=ready,
    )
    assert lab.snapshot()["guaranteedTopic"].startswith("ssa-guaranteed/unclass/")
    assert lab.snapshot()["guaranteedAvailable"] is False
    local = LiveLab(
        LabConfig(
            host="tcp://127.0.0.1:9",
            vpn="default",
            semp_url="http://127.0.0.1:9",
            admin_user="admin",
            admin_password="local-only",
            publisher_username="pub-user",
            publisher_password="pub-secret",
            subscriber_username="op-user",
            subscriber_password="op-secret",
            allow_remote=False,
        )
    )
    assert local.guaranteed_prefix == ""
    assert local.snapshot()["guaranteedTopic"] == "ssa/unclass/ground1/launch/25544/alert"


def test_ready_guaranteed_note_survives_state_sanitization(monkeypatch):
    from solace_demo.config import LabConfig
    from solace_demo.live import LiveLab
    from solace_demo.web import public_payload

    _base(monkeypatch)
    monkeypatch.setenv("SOLACE_OPERATOR_QUEUE", "queue-local-operator-guaranteed")
    monkeypatch.setenv("SOLACE_GUARANTEED_TOPIC_PREFIX", "ssa-guaranteed/unclass")
    split = load_split_client()
    config = LabConfig(
        host="tcp://127.0.0.1:9",
        vpn="default",
        semp_url="http://127.0.0.1:9",
        admin_user="admin",
        admin_password="local-only",
        publisher_username="pub-user",
        publisher_password="pub-secret",
        subscriber_username="op-user",
        subscriber_password="op-secret",
        allow_remote=False,
    )
    state = LiveLab(config, split=split).snapshot()
    cleaned = public_payload(state, config, tuple(split.secrets()))
    note = state["guaranteedNote"]
    assert cleaned["guaranteedNote"] == note
    assert note == (
        "Topic ssa-guaranteed/unclass/ground1/launch/25544/alert. "
        "Queue queue-local-operator-guaranteed holds it while this console is offline. "
        "A broker ACK means the broker accepted it. This console shows the alert when it arrives."
    )
    assert note.endswith(".")
    assert len(note) <= 240
    assert "exactly" not in note.lower()
    assert "while the bridge" not in note.lower()


def test_loopback_pair_is_labeled_disposable_and_leaves_guaranteed_off(monkeypatch):
    _base(monkeypatch)
    monkeypatch.setenv("SOLACE_HOST", "tcp://127.0.0.1:15555")
    monkeypatch.setenv("SOLACE_SEMP_URL", "http://127.0.0.1:18080")
    split = load_split_client()
    assert split.publisher.host.endswith(":16655")
    assert split.operator.host.endswith(":16755")
    assert "15555" not in split.publisher.host
    assert "18080" not in split.publisher.host
    label = split.mode_label()
    assert "Disposable two-endpoint test" in label
    assert "Not the cloud service" in label
    assert split.operator_queue == ""
    assert "existing operator queue" in split.guaranteed_note()
    assert split.queue_count() is None
    props = split.publisher.client_properties()
    assert CERT_VALIDATED not in props or props.get(CERT_VALIDATED) is not False
    assert props["solace.messaging.transport.host"].startswith("tcp://127.0.0.1:16655")


def test_guaranteed_control_does_not_publish_without_an_operator_queue(monkeypatch):
    _base(monkeypatch)
    from solace_demo.config import LabConfig
    from solace_demo.live import LiveLab

    split = load_split_client()

    class Dummy:
        is_connected = True

    lab = LiveLab(
        LabConfig(
            host="tcp://127.0.0.1:9",
            vpn="default",
            semp_url="http://127.0.0.1:9",
            admin_user="admin",
            admin_password="local-only",
            publisher_username="pub-user",
            publisher_password="pub-secret",
            subscriber_username="op-user",
            subscriber_password="op-secret",
            allow_remote=False,
        ),
        split=split,
    )
    lab._publisher = Dummy()
    lab._subscriber = Dummy()
    lab.broker_connected = True
    lab._probed_at = 10**12
    result = lab.send("guaranteed-launch")
    assert result["outcome"] == "not-sent"
    assert result["brokerAck"] is False
    assert "existing operator queue" in result["customerText"]
    assert lab.snapshot()["events"] == []
    assert lab.snapshot()["guaranteedAvailable"] is False
    assert lab.snapshot()["queueDepth"] is None


def test_loopback_operator_connects_without_a_password_when_broker_has_no_auth():
    import os

    host = os.environ.get("SOLACE_TEST_NOAUTH_HOST", "") or os.environ.get("SOLACE_TEST_OPERATOR_HOST", "")
    semp = os.environ.get("SOLACE_TEST_NOAUTH_SEMP", "") or os.environ.get("SOLACE_TEST_OPERATOR_SEMP", "")
    admin = os.environ.get("SOLACE_TEST_NOAUTH_PASSWORD", "") or os.environ.get("SOLACE_TEST_BROKER_PASSWORD", "")
    if not all((host, semp, admin)):
        pytest.skip("disposable operator broker is not set")
    from solace_demo.config import LabConfig
    from solace_demo.messaging import connect, disconnect
    from solace_demo.provision import wait_until_ready
    from solace_demo.semp import Semp

    config = LabConfig(
        host=host,
        vpn="default",
        semp_url=semp,
        admin_user="admin",
        admin_password=admin,
        publisher_username="ssa-publisher",
        publisher_password=admin,
        subscriber_username="default",
        subscriber_password="",
        allow_remote=False,
    )
    wait_until_ready(config, attempts=5, pause_seconds=1)
    client = Semp(config)
    client.request(
        "PUT",
        "/SEMP/v2/config/msgVpns/default",
        {"enabled": True, "authenticationBasicEnabled": True, "authenticationBasicType": "none"},
    )
    service = connect(config, "default", "")
    try:
        assert service.is_connected
    finally:
        disconnect([service])


def test_two_disposable_endpoints_do_not_share_a_receipt():
    import os
    import threading
    import time

    pub_host = os.environ.get("SOLACE_TEST_PUBLISHER_HOST", "")
    op_host = os.environ.get("SOLACE_TEST_OPERATOR_HOST", "")
    pub_semp = os.environ.get("SOLACE_TEST_PUBLISHER_SEMP", "")
    op_semp = os.environ.get("SOLACE_TEST_OPERATOR_SEMP", "")
    password = os.environ.get("SOLACE_TEST_BROKER_PASSWORD", "")
    if not all((pub_host, op_host, pub_semp, op_semp, password)):
        pytest.skip("disposable two-broker endpoints are not set")
    from solace_demo.config import LabConfig
    from solace_demo.live import LiveLab
    from solace_demo.messaging import collect_direct, connect, disconnect
    from solace_demo.provision import provision, wait_until_ready
    from solace_demo.semp import Semp, SempError
    from solace_demo.catalog import LAUNCH_SUBSCRIPTION

    def lab_config(host, semp):
        return LabConfig(
            host=host,
            vpn="default",
            semp_url=semp,
            admin_user="admin",
            admin_password=password,
            publisher_username="ssa-publisher",
            publisher_password=password,
            subscriber_username="ssa-subscriber",
            subscriber_password=password,
            allow_remote=False,
        )

    publisher_config = lab_config(pub_host, pub_semp)
    operator_config = lab_config(op_host, op_semp)
    wait_until_ready(publisher_config, attempts=5, pause_seconds=1)
    wait_until_ready(operator_config, attempts=5, pause_seconds=1)
    provision(publisher_config)
    provision(operator_config)
    for config in (publisher_config, operator_config):
        with pytest.raises(SempError):
            Semp(config).request("GET", "/SEMP/v2/config/msgVpns/default/queues/q-ssa-web-console")
    monkeypatch = pytest.MonkeyPatch()
    _base(
        monkeypatch,
        publisher=pub_host,
        operator=op_host,
    )
    monkeypatch.setenv("SOLACE_PUBLISHER_USERNAME", "ssa-publisher")
    monkeypatch.setenv("SOLACE_PUBLISHER_PASSWORD", password)
    monkeypatch.setenv("SOLACE_OPERATOR_USERNAME", "ssa-subscriber")
    monkeypatch.setenv("SOLACE_OPERATOR_PASSWORD", password)
    monkeypatch.setenv("SOLACE_PUBLISHER_VPN", "default")
    monkeypatch.setenv("SOLACE_OPERATOR_VPN", "default")
    split = load_split_client()
    assert split.management_changes is False
    lab = LiveLab(
        LabConfig(
            host="tcp://127.0.0.1:9",
            vpn="default",
            semp_url="http://127.0.0.1:9",
            admin_user="admin",
            admin_password=password,
            publisher_username="ssa-publisher",
            publisher_password=password,
            subscriber_username="ssa-subscriber",
            subscriber_password=password,
            allow_remote=False,
        ),
        split=split,
    )
    lab.open()
    try:
        names = _client_usernames(publisher_config)
        assert "ssa-publisher" in names
        assert "ssa-subscriber" not in names
        names = _client_usernames(operator_config)
        assert "ssa-subscriber" in names
        assert "ssa-publisher" not in names
        box = {}

        def listen():
            service = connect(publisher_config, "ssa-subscriber", password)
            try:
                box["ids"] = collect_direct(service, LAUNCH_SUBSCRIPTION, 3000)
            finally:
                disconnect([service])

        listener = threading.Thread(target=listen)
        listener.start()
        time.sleep(0.4)
        sent = lab.send("launch-ground1")
        assert sent["outcome"] == "sent"
        assert sent["brokerAck"] is False
        listener.join(timeout=5)
        time.sleep(0.6)
        assert lab.snapshot()["events"] == []
        assert sent["alertId"] in box.get("ids", [])
    finally:
        lab.close()
        monkeypatch.undo()


def _client_usernames(config):
    from solace_demo.semp import Semp

    payload = Semp(config, timeout=3.0).request("GET", "/SEMP/v2/monitor/msgVpns/default/clients")
    return {item.get("clientUsername") for item in payload.get("data") or []}
