"""Create the demo VPN objects. Admin is used here and nowhere in the message path."""

from __future__ import annotations

import os

from solace_demo.catalog import (
    ALLOWED_EXCEPTION,
    PUBLISHER_CLIENT_PROFILE,
    PUBLISHER_PROFILE,
    QUEUE_NAME,
    QUEUE_SUBSCRIPTION,
    WEB_QUEUE_NAME,
    SUBSCRIBER_CLIENT_PROFILE,
    SUBSCRIBER_PROFILE,
)
from solace_demo.config import LabConfig, _loopback
from solace_demo.semp import Semp, SempError


class ProvisionError(RuntimeError):
    """A management write was refused."""


def broker_is_remote(config: LabConfig) -> bool:
    """True for a Cloud broker or any host that is not loopback."""
    return bool(config.allow_remote) or not _loopback(config.host)


def _remote_client_update_opt_in(explicit: bool | None) -> bool:
    if explicit is True:
        return True
    if explicit is False:
        return False
    return os.environ.get("SOLACE_ALLOW_REMOTE_CLIENT_UPDATE", "").strip().lower() in {"1", "true", "yes"}


def _shared_usernames(config: LabConfig) -> set[str]:
    return {name for name in (config.publisher_username, config.subscriber_username) if name}


def _vpn(config: LabConfig, suffix: str) -> str:
    return f"/SEMP/v2/config/msgVpns/{config.vpn}{suffix}"


def ensure_client_profile(semp: Semp, config: LabConfig, name: str, send: bool, receive: bool) -> None:
    body = {
        "clientProfileName": name,
        "allowGuaranteedMsgSendEnabled": send,
        "allowGuaranteedMsgReceiveEnabled": receive,
        "allowGuaranteedEndpointCreateEnabled": False,
        "allowTransactedSessionsEnabled": False,
        "maxConnectionCountPerClientUsername": 10,
        "serviceSmfMaxConnectionCountPerClientUsername": 10,
    }
    try:
        semp.request("POST", _vpn(config, "/clientProfiles"), body, ok_exists=True)
    except SempError:
        semp.request("PUT", _vpn(config, f"/clientProfiles/{name}"), body)


def ensure_acl_profile(semp: Semp, config: LabConfig, name: str) -> None:
    body = {
        "aclProfileName": name,
        "clientConnectDefaultAction": "allow",
        "publishTopicDefaultAction": "disallow",
        "subscribeTopicDefaultAction": "disallow",
        # This broker has no publishShareNameDefaultAction. Share-name subscribe
        # stays disallow so a shared subscription is not an accidental allow.
        "subscribeShareNameDefaultAction": "disallow",
    }
    try:
        semp.request("POST", _vpn(config, "/aclProfiles"), body, ok_exists=True)
    except SempError:
        semp.request("PUT", _vpn(config, f"/aclProfiles/{name}"), body)


def ensure_topic_exception(
    semp: Semp,
    config: LabConfig,
    profile: str,
    direction: str,
    exception: str,
) -> None:
    if direction == "publish":
        body = {"publishTopicExceptionSyntax": "smf", "publishTopicException": exception}
        path = f"/aclProfiles/{profile}/publishTopicExceptions"
    elif direction == "subscribe":
        body = {"subscribeTopicExceptionSyntax": "smf", "subscribeTopicException": exception}
        path = f"/aclProfiles/{profile}/subscribeTopicExceptions"
    else:
        raise ValueError(direction)
    semp.request("POST", _vpn(config, path), body, ok_exists=True)


def _client_username_exists(semp: Semp, config: LabConfig, username: str) -> bool:
    try:
        semp.request("GET", _vpn(config, f"/clientUsernames/{username}"))
    except SempError as exc:
        if exc.status == 404:
            return False
        raise
    return True


def ensure_client_username(
    semp: Semp,
    config: LabConfig,
    username: str,
    password: str,
    acl_profile: str,
    client_profile: str,
    allow_remote_update: bool | None = None,
) -> None:
    body = {
        "clientUsername": username,
        "password": password,
        "enabled": True,
        "aclProfileName": acl_profile,
        "clientProfileName": client_profile,
    }
    path = _vpn(config, "/clientUsernames")
    user_path = _vpn(config, f"/clientUsernames/{username}")
    if broker_is_remote(config):
        if username in _shared_usernames(config):
            raise ProvisionError(
                f"Refusing to modify client username {username} on a non-loopback broker."
            )
        exists = _client_username_exists(semp, config, username)
        if exists and not _remote_client_update_opt_in(allow_remote_update):
            raise ProvisionError(
                f"Refusing to modify existing client username {username} on a non-loopback broker. "
                "Set SOLACE_ALLOW_REMOTE_CLIENT_UPDATE=1 to opt in."
            )
        if not exists:
            semp.request("POST", path, body, ok_exists=True)
        if exists or _remote_client_update_opt_in(allow_remote_update):
            # PUT replaces the password on an opted-in rerun. The body is not logged.
            semp.request("PUT", user_path, body)
        return
    try:
        semp.request("POST", path, body, ok_exists=True)
    except SempError:
        pass
    # PUT replaces the password on reruns. The body is not logged.
    semp.request("PUT", user_path, body)


def _when_spool_ready(action):
    """Message spool can lag the SEMP about endpoint on container start."""
    import time

    last = None
    for _ in range(30):
        try:
            return action()
        except SempError as exc:
            if "message spool" not in exc.description.lower():
                raise
            last = exc
            time.sleep(2)
    raise last


def _ensure_queue(semp: Semp, config: LabConfig, name: str) -> None:
    """Create the queue if it is missing. Do not delete messages already on it."""
    if broker_is_remote(config):
        return
    body = {
        "queueName": name,
        "accessType": "exclusive",
        "permission": "no-access",
        "ingressEnabled": True,
        "egressEnabled": True,
        "owner": config.subscriber_username,
    }

    def create_or_replace() -> None:
        try:
            semp.request("POST", _vpn(config, "/queues"), body, ok_exists=True)
        except SempError:
            semp.request("PUT", _vpn(config, f"/queues/{name}"), body)

    _when_spool_ready(create_or_replace)
    _when_spool_ready(
        lambda: semp.request(
            "POST",
            _vpn(config, f"/queues/{name}/subscriptions"),
            {"subscriptionTopic": QUEUE_SUBSCRIPTION},
            ok_exists=True,
        )
    )


def ensure_queue(semp: Semp, config: LabConfig) -> None:
    _ensure_queue(semp, config, QUEUE_NAME)


def ensure_web_queue(semp: Semp, config: LabConfig) -> None:
    """Browser queue only. Does not delete or bind q-ssa-operator."""
    _ensure_queue(semp, config, WEB_QUEUE_NAME)


def recreate_queue(semp: Semp, config: LabConfig) -> None:
    """Drop and recreate only the demo queue so a rerun starts empty."""
    if broker_is_remote(config):
        raise ProvisionError("Refusing to delete a queue on a non-loopback broker.")
    def delete_queue() -> None:
        try:
            semp.request("DELETE", _vpn(config, f"/queues/{QUEUE_NAME}"))
        except SempError as exc:
            if exc.status != 404:
                raise

    _when_spool_ready(delete_queue)
    ensure_queue(semp, config)


def assert_shared_clients_unchanged(config: LabConfig, usernames: list[str] | None = None) -> None:
    """Fail when a shared client is no longer on the default profile and ACL."""
    names = usernames if usernames is not None else [config.publisher_username, config.subscriber_username]
    semp = Semp(config)
    problems = []
    for name in names:
        if not name:
            continue
        payload = semp.request("GET", _vpn(config, f"/clientUsernames/{name}"))
        data = payload.get("data") if isinstance(payload, dict) else None
        record = data if isinstance(data, dict) else {}
        client_profile = str(record.get("clientProfileName") or "")
        acl_profile = str(record.get("aclProfileName") or "")
        if client_profile != "default" or acl_profile != "default":
            problems.append(
                f"{name} clientProfileName={client_profile or 'missing'} aclProfileName={acl_profile or 'missing'}"
            )
    if problems:
        raise ProvisionError(
            "Shared client usernames were changed on this broker: "
            + "; ".join(problems)
            + ". Expected clientProfileName=default and aclProfileName=default."
        )


def provision(config: LabConfig) -> list[str]:
    if broker_is_remote(config):
        return [
            f"Message VPN {config.vpn}",
            "Remote broker: shared client usernames, profiles, ACLs, and passwords were left as configured.",
        ]
    semp = Semp(config)
    ensure_client_profile(semp, config, PUBLISHER_CLIENT_PROFILE, send=True, receive=False)
    ensure_client_profile(semp, config, SUBSCRIBER_CLIENT_PROFILE, send=False, receive=True)
    ensure_acl_profile(semp, config, PUBLISHER_PROFILE)
    ensure_acl_profile(semp, config, SUBSCRIBER_PROFILE)
    ensure_topic_exception(semp, config, PUBLISHER_PROFILE, "publish", ALLOWED_EXCEPTION)
    ensure_topic_exception(semp, config, SUBSCRIBER_PROFILE, "subscribe", ALLOWED_EXCEPTION)
    ensure_client_username(
        semp,
        config,
        config.publisher_username,
        config.publisher_password,
        PUBLISHER_PROFILE,
        PUBLISHER_CLIENT_PROFILE,
    )
    ensure_client_username(
        semp,
        config,
        config.subscriber_username,
        config.subscriber_password,
        SUBSCRIBER_PROFILE,
        SUBSCRIBER_CLIENT_PROFILE,
    )
    ensure_queue(semp, config)
    return [
        f"Message VPN {config.vpn}",
        f"ACL {PUBLISHER_PROFILE}: publish default disallow, exception allow {ALLOWED_EXCEPTION}; subscribe default disallow, no exception",
        f"ACL {SUBSCRIBER_PROFILE}: subscribe default disallow, exception allow {ALLOWED_EXCEPTION}; publish default disallow, no exception",
        "Client connect default on both profiles: allow",
        f"Queue {QUEUE_NAME} owner={config.subscriber_username} permission=no-access subscription={QUEUE_SUBSCRIPTION}",
        "Queue permission is separate from the topic ACL. Subscribe-topic ACLs are not what grants this queue bind.",
        "Admin credentials were used for SEMP only.",
    ]


def wait_until_ready(config: LabConfig, attempts: int = 60, pause_seconds: float = 2.0) -> None:
    import time

    semp = Semp(config, timeout=3.0)
    last = "SEMP has not answered"
    for _ in range(attempts):
        try:
            semp.request("GET", "/SEMP/v2/config/about")
            return
        except (SempError, OSError, TimeoutError) as exc:
            last = str(exc)
            time.sleep(pause_seconds)
    raise SempError("GET", "/SEMP/v2/config/about", 0, f"broker not ready: {last}")


def monitor_live_clients(config: LabConfig, username: str) -> list[str]:
    """Read ACL discard counters from sessions that are still connected."""
    semp = Semp(config)
    path = f"/SEMP/v2/monitor/msgVpns/{config.vpn}/clients?count=50"
    try:
        payload = semp.request("GET", path)
    except SempError as exc:
        return [f"MONITOR {username}: clients query unavailable ({exc.status}: {exc.description})"]
    lines = []
    for client in payload.get("data") or []:
        if client.get("clientUsername") != username:
            continue
        lines.append(
            "MONITOR {user} client={name} aclProfile={profile} "
            "publishTopicAclRxDiscardedMsgCount={denied} rxDiscardedMsgCount={rx}".format(
                user=username,
                name=client.get("clientName"),
                profile=client.get("aclProfileName"),
                denied=client.get("publishTopicAclRxDiscardedMsgCount"),
                rx=client.get("rxDiscardedMsgCount"),
            )
        )
    if not lines:
        lines.append(f"MONITOR {username}: no connected client session to count")
    return lines
