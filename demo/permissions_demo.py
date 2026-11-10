"""One typed command, one Solace attempt.

The button is not this program. Each invocation connects once as --client,
performs only that action, prints the broker's result, and disconnects.
It does not advance to the next action.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

from solace.messaging.config.solace_properties import (
    authentication_properties,
    message_properties,
    service_properties,
    transport_layer_properties,
)
from solace.messaging.config.solace_properties.transport_layer_security_properties import (
    CERT_REJECT_EXPIRED,
    CERT_VALIDATED,
    CERT_VALIDATE_SERVERNAME,
)
from solace.messaging.config.sub_code import SolClientSubCode
from solace.messaging.config.transport_security_strategy import TLS
from solace.messaging.messaging_service import MessagingService
from solace.messaging.resources.topic import Topic
from solace.messaging.resources.topic_subscription import TopicSubscription

from solace_demo.config import _merged
from solace_demo.split_client import demo_broker_label, display_broker_label

SUBSCRIBE_DENIAL = "SOLCLIENT_SUBCODE_SUBSCRIPTION_ACL_DENIED"
PUBLISH_DENIAL = "SOLCLIENT_SUBCODE_PUBLISH_ACL_DENIED"
ALLOWED_PREFIX = "solace-demo/permissions/allowed/>"
ALLOWED_TOPIC = "solace-demo/permissions/allowed/proof"
DENIED_TOPIC = "solace-demo/permissions/denied/proof"
WEB_ACTIONS = {
    "allowed-send": ALLOWED_TOPIC,
    "subscribe": DENIED_TOPIC,
    "publish-guaranteed": DENIED_TOPIC,
}
_WEB_LOCK = threading.Lock()
RECEIVE_TIMEOUT_MS = 5000
PUBLISH_TIMEOUT_MS = 5000

ROOT = Path.home() / ".solace-demo" / "private" / "permissions"
DEFAULT_CONFIG = ROOT / "client-cloud-permissions-demo.json"
DEFAULT_TRUST = ROOT / "trusted-ca"
DEFAULT_EVIDENCE = ROOT / "evidence"


class DemoFailure(Exception):
    def __init__(self, lines: list):
        super().__init__("failed")
        self.lines = lines


def parse_args(argv: list) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="permissions_demo.py")
    parser.add_argument("action", choices=("allowed-send", "subscribe", "publish-guaranteed"))
    parser.add_argument("--client", required=True)
    parser.add_argument("--topic", required=True)
    return parser.parse_args(argv)


def _control(value: str) -> bool:
    return any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in value)


def config_path() -> Path:
    override = os.environ.get("SOLACE_PERMISSIONS_CONFIG", "").strip()
    return Path(override) if override else DEFAULT_CONFIG


def trust_path() -> Path:
    override = os.environ.get("SOLACE_PERMISSIONS_TRUST_STORE", "").strip()
    return Path(override) if override else DEFAULT_TRUST


def load_credentials(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise DemoFailure(["result=failed", "sdk=credential file could not be read"])
    if not isinstance(data, dict):
        raise DemoFailure(["result=failed", "sdk=credential file is not an object"])
    missing = [key for key in ("host", "password", "username", "vpn") if not isinstance(data.get(key), str) or not data.get(key)]
    if missing:
        raise DemoFailure(["result=failed", "sdk=credential file is missing " + " ".join(missing)])
    for key in ("host", "password", "username", "vpn"):
        if _control(data[key]):
            raise DemoFailure(["result=failed", "sdk=credential field has a control character"])
    host = data["host"]
    tail = host.split("://", 1)[-1]
    if "://" not in host or "@" in tail or "/" in tail.split(":", 1)[-1]:
        raise DemoFailure(["result=failed", "sdk=host must be tcps:// with a port and no userinfo"])
    scheme = host.split("://", 1)[0].lower()
    loopback = tail.startswith("127.0.0.1:") or tail.startswith("localhost:") or tail.startswith("[::1]:")
    allow_loopback = os.environ.get("SOLACE_PERMISSIONS_ALLOW_LOOPBACK", "").strip() == "1"
    if scheme == "tcp" and loopback and allow_loopback:
        return data
    if scheme != "tcps":
        raise DemoFailure(["result=failed", "sdk=host must be tcps:// with a port and no userinfo"])
    return data


def require_client(creds: dict, client: str) -> None:
    if creds["username"] != client:
        raise DemoFailure(["result=failed", "sdk=username does not match --client"])


def session_properties(creds: dict) -> dict:
    props = {
        transport_layer_properties.HOST: creds["host"],
        service_properties.VPN_NAME: creds["vpn"],
        authentication_properties.SCHEME_BASIC_USER_NAME: creds["username"],
        authentication_properties.SCHEME_BASIC_PASSWORD: creds["password"],
        transport_layer_properties.CONNECTION_RETRIES: 0,
        transport_layer_properties.RECONNECTION_ATTEMPTS: 0,
        transport_layer_properties.CONNECTION_ATTEMPTS_TIMEOUT: 8000,
    }
    return props


def tls_configuration(trust: Path) -> dict:
    checked = TLS.create().with_certificate_validation(False, True, str(trust)).security_configuration
    if checked.get(CERT_VALIDATED) is not True or checked.get(CERT_VALIDATE_SERVERNAME) is not True:
        raise DemoFailure(["result=failed", "sdk=certificate validation did not stay enabled"])
    if checked.get(CERT_REJECT_EXPIRED) is not True:
        raise DemoFailure(["result=failed", "sdk=certificate validation did not stay enabled"])
    return checked


def connect_service(creds: dict) -> MessagingService:
    builder = MessagingService.builder().from_properties(session_properties(creds))
    if creds["host"].lower().startswith("tcps://"):
        trust = trust_path()
        if not trust.is_dir():
            raise DemoFailure(["result=failed", "sdk=trust store directory is missing"])
        builder = builder.with_transport_security_strategy(
            TLS.create().with_certificate_validation(False, True, str(trust))
        )
        tls_configuration(trust)
    service = builder.build()
    service.connect()
    return service


def fresh_id() -> str:
    return "perm-" + uuid.uuid4().hex[:12]


def message_for(service: MessagingService, alert_id: str, topic: str):
    body = json.dumps({"alertId": alert_id, "topic": topic}, separators=(",", ":"), sort_keys=True)
    return (
        service.message_builder()
        .from_properties(
            {
                message_properties.APPLICATION_MESSAGE_ID: alert_id,
                message_properties.CORRELATION_ID: alert_id,
            }
        )
        .build(body)
    )


def sdk_text(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}".replace("\n", " ")


def denial_token(exc: BaseException) -> str:
    """Name the ACL denial only when the SDK subcode says so."""
    code = getattr(exc, "sub_code", None)
    if code in (
        SolClientSubCode.SOLCLIENT_SUBCODE_SUBSCRIPTION_ACL_DENIED,
        SolClientSubCode.SOLCLIENT_SUBCODE_SUBSCRIPTION_ACL_DENIED.value,
    ):
        return SUBSCRIBE_DENIAL
    if code in (
        SolClientSubCode.SOLCLIENT_SUBCODE_PUBLISH_ACL_DENIED,
        SolClientSubCode.SOLCLIENT_SUBCODE_PUBLISH_ACL_DENIED.value,
    ):
        return PUBLISH_DENIAL
    text = sdk_text(exc)
    if SUBSCRIBE_DENIAL in text:
        return SUBSCRIBE_DENIAL
    if PUBLISH_DENIAL in text:
        return PUBLISH_DENIAL
    return ""


def visible_sdk(exc: BaseException) -> str:
    token = denial_token(exc)
    if token == SUBSCRIBE_DENIAL:
        return type(exc).__name__ + ": Subscription ACL Denied " + token
    if token == PUBLISH_DENIAL:
        return type(exc).__name__ + ": Publish ACL Denied " + token
    return sdk_text(exc)


class _DropSdkLog(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not record.name.startswith("solace")


def silence_sdk_logs() -> None:
    """Keep SDK log lines off the terminal. The sanitized result is the error."""
    names = ["solace"]
    names.extend(
        name for name in list(logging.Logger.manager.loggerDict) if name.startswith("solace.")
    )
    for name in names:
        log = logging.getLogger(name)
        log.handlers.clear()
        log.setLevel(logging.CRITICAL)
        log.propagate = False
    root = logging.getLogger()
    if not any(isinstance(item, _DropSdkLog) for item in root.filters):
        root.addFilter(_DropSdkLog())
    for handler in root.handlers:
        if not any(isinstance(item, _DropSdkLog) for item in handler.filters):
            handler.addFilter(_DropSdkLog())


def message_id_and_topic(incoming) -> tuple:
    """Read the id and topic from the message that arrived."""
    got_topic = incoming.get_destination_name() or ""
    got_id = incoming.get_correlation_id() or ""
    if got_id:
        return str(got_id), str(got_topic)
    raw = incoming.get_payload_as_string() or ""
    if not raw:
        try:
            blob = incoming.get_payload_as_bytes()
        except Exception:
            blob = b""
        if blob:
            raw = bytes(blob).decode("utf-8")
    try:
        body = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, UnicodeError):
        body = {}
    if isinstance(body, dict) and body.get("alertId"):
        got_id = str(body["alertId"])
    return got_id, str(got_topic)


def receipt_lines(sent_id: str, incoming, published_topic: str) -> list:
    got_id, got_topic = message_id_and_topic(incoming)
    matched = got_id == sent_id and got_topic == published_topic and got_topic != ""
    lines = [
        "sent_id=" + sent_id,
        "received_id=" + got_id,
        "received_topic=" + got_topic,
        "result=received" if matched else "result=mismatch",
    ]
    if not matched:
        lines.append("sdk=received id or topic did not match the publish")
    return lines


def allowed_send(service: MessagingService, topic: str) -> list:
    alert_id = fresh_id()
    receiver = (
        service.create_direct_message_receiver_builder()
        .with_subscriptions([TopicSubscription.of(topic)])
        .build()
    )
    receiver.start()
    publisher = None
    try:
        publisher = service.create_direct_message_publisher_builder().build()
        publisher.start()
        publisher.publish(message_for(service, alert_id, topic), Topic.of(topic))
        incoming = receiver.receive_message(timeout=RECEIVE_TIMEOUT_MS)
    finally:
        if publisher is not None:
            publisher.terminate()
        receiver.terminate()
    if incoming is None:
        raise DemoFailure(["sent_id=" + alert_id, "result=missing", "sdk=no message arrived"])
    lines = receipt_lines(alert_id, incoming, topic)
    if "result=received" not in lines:
        raise DemoFailure(lines + ["send_returned=yes", "broker_ack=no"])
    return lines + ["send_returned=yes", "broker_ack=no"]


def subscribe_once(service: MessagingService, topic: str) -> list:
    receiver = service.create_direct_message_receiver_builder().build()
    receiver.start()
    try:
        receiver.add_subscription(TopicSubscription.of(topic))
    except Exception as exc:
        text = visible_sdk(exc)
        if denial_token(exc) == SUBSCRIBE_DENIAL:
            return ["result=denied", "sdk=" + text, "send_returned=no", "broker_ack=no"]
        raise DemoFailure(["result=failed", "sdk=" + text])
    finally:
        receiver.terminate()
    raise DemoFailure(["result=accepted", "sdk=broker accepted the subscription"])


def publish_guaranteed_once(service: MessagingService, topic: str) -> list:
    alert_id = fresh_id()
    publisher = service.create_persistent_message_publisher_builder().on_back_pressure_reject(10).build()
    publisher.start()
    try:
        publisher.publish_await_acknowledgement(
            message_for(service, alert_id, topic),
            Topic.of(topic),
            time_out=PUBLISH_TIMEOUT_MS,
        )
    except Exception as exc:
        text = visible_sdk(exc)
        if denial_token(exc) == PUBLISH_DENIAL:
            return ["id=" + alert_id, "result=denied", "sdk=" + text, "send_returned=no", "broker_ack=no"]
        raise DemoFailure(["id=" + alert_id, "result=failed", "sdk=" + text, "send_returned=no", "broker_ack=no"])
    finally:
        publisher.terminate()
    raise DemoFailure([
        "id=" + alert_id,
        "result=acked",
        "sdk=broker acknowledged the publish",
        "send_returned=yes",
        "broker_ack=yes",
    ])


def secrets_of(creds: dict) -> list:
    values = [creds.get("password", ""), creds.get("host", ""), creds.get("vpn", "")]
    host = creds.get("host", "")
    if "://" in host:
        values.append(host.split("://", 1)[1].split(":")[0])
    values.append(str(config_path()))
    values.append(str(trust_path()))
    return [item for item in values if item]


def sanitize(text: str, secrets: list) -> str:
    clean = text.replace("\n", " ")
    for secret in secrets:
        if secret:
            clean = clean.replace(secret, "[redacted]")
    return clean


def evidence_file(action: str) -> Path:
    override = os.environ.get("SOLACE_PERMISSIONS_EVIDENCE_DIR", "").strip()
    directory = Path(override) if override else DEFAULT_EVIDENCE
    directory.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    for _ in range(5):
        path = directory / f"{stamp}-{os.getpid()}-{action}-{uuid.uuid4().hex[:8]}.log"
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
            return path
        except FileExistsError:
            continue
    raise DemoFailure(["result=failed", "sdk=could not create an evidence file"])


def emit(action: str, client: str, topic: str, lines: list, creds: dict, private_note: str = "") -> None:
    secrets = secrets_of(creds) if creds else []
    output = [f"actor={client}", f"action={action}", f"topic={topic}"] + lines
    text = "\n".join(sanitize(line, secrets) for line in output) + "\n"
    sys.stdout.write(text)
    path = evidence_file(action)
    hidden = sanitize(private_note, secrets).strip()
    if hidden:
        text += "\n# private diagnostic, not shown on the terminal\n" + hidden + "\n"
    path.write_text(text, encoding="utf-8")


def _read_captured(handle) -> str:
    try:
        handle.flush()
        handle.seek(0)
        data = handle.read()
    except Exception:
        return ""
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace")
    return str(data)


def _enabled() -> bool:
    return os.environ.get("SOLACE_PERMISSIONS_DEMO", "").strip().lower() in {"1", "true", "yes"}


def permissions_status() -> dict:
    """Read the opt-in flag and username. Do not connect."""
    shown = {
        "permissionsEnabled": False,
        "permissionsReady": False,
        "permissionsClient": "",
        "permissionsAllowPrefix": "",
        "permissionsAllowedTopic": "",
        "permissionsDeniedTopic": "",
        "permissionsPolicyNote": "",
        "permissionsBroker": "",
        "permissionsBrokerLabel": "",
        "permissionsPath": "",
        "permissionsProblem": "",
    }
    if not _enabled() or os.environ.get("SOLACE_WEB_ROLE", "").strip().lower() == "publisher":
        return shown
    shown["permissionsEnabled"] = True
    shown["permissionsAllowPrefix"] = ALLOWED_PREFIX
    shown["permissionsAllowedTopic"] = ALLOWED_TOPIC
    shown["permissionsDeniedTopic"] = DENIED_TOPIC
    shown["permissionsPolicyNote"] = (
        "Connect is allowed. Publish and subscribe are allowed on " + ALLOWED_PREFIX
        + " and denied on other topics."
    )
    try:
        creds = load_credentials(config_path())
    except DemoFailure as exc:
        shown["permissionsProblem"] = exc.lines[-1].split("=", 1)[-1]
        shown["permissionsPath"] = "The restricted client is not configured. Nothing is connected."
        return shown
    shown["permissionsReady"] = True
    shown["permissionsClient"] = creds["username"]
    shown["permissionsBroker"] = demo_broker_label(creds["host"])
    shown["permissionsBrokerLabel"] = display_broker_label(
        creds["host"], _merged("SOLACE_PERMISSIONS_BROKER_LABEL", "")
    )
    shown["permissionsPath"] = "Each click connects as this client and then disconnects."
    return shown


def _public_result(action: str, client: str, topic: str, lines: list, creds: dict) -> dict:
    secrets = secrets_of(creds) if creds else []

    def take(prefix: str) -> str:
        for line in lines:
            if line.startswith(prefix):
                return sanitize(line.split("=", 1)[1], secrets)
        return ""

    result = take("result=") or "failed"
    # A direct receipt is not a broker acknowledgement. Only an awaited publish that returned is.
    broker_ack = take("broker_ack=") == "yes" and result == "acked"
    closed = take("session_closed=")
    return {
        "result": result,
        "actor": client,
        "action": action,
        "topic": topic,
        "sentId": take("sent_id="),
        "receivedId": take("received_id="),
        "receivedTopic": take("received_topic="),
        "sdk": take("sdk="),
        "connectionVerified": take("connection=") == "verified",
        "sessionClosed": True if closed == "yes" else False if closed == "no" else None,
        "closureSdk": take("closure_sdk="),
        "sendReturned": take("send_returned=") == "yes",
        "brokerAck": broker_ack,
    }


def broker_attempt(action: str, topic: str, client: str) -> tuple:
    """One broker attempt. Returns exit code, result lines, credentials, and hidden diagnostics."""
    creds = {}
    lines = ["result=failed", "sdk=the command did not finish"]
    code = 1
    private_note = ""
    previous_disable = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    silence_sdk_logs()
    saved_fd = os.dup(2)
    captured = tempfile.TemporaryFile()
    old_err = sys.stderr
    os.dup2(captured.fileno(), 2)
    sys.stderr = captured
    service = None
    authenticated = False
    closed = None
    closure_error = ""
    try:
        creds = load_credentials(config_path())
        require_client(creds, client)
        service = connect_service(creds)
        try:
            authenticated = service.is_connected is True
        except Exception as exc:
            lines = ["result=failed", "sdk=" + sdk_text(exc)]
            code = 1
            authenticated = False
        else:
            if not authenticated:
                lines = ["result=failed", "sdk=the broker did not report an authenticated session"]
                code = 1
            else:
                try:
                    if action == "allowed-send":
                        lines = allowed_send(service, topic)
                    elif action == "subscribe":
                        lines = subscribe_once(service, topic)
                    elif action == "publish-guaranteed":
                        lines = publish_guaranteed_once(service, topic)
                    else:
                        raise DemoFailure(["result=failed", "sdk=unknown action"])
                    code = 0
                except DemoFailure as exc:
                    lines = list(exc.lines)
                    code = 1
                except Exception as exc:
                    lines = ["result=failed", "sdk=" + sdk_text(exc)]
                    code = 1
    except DemoFailure as exc:
        lines = list(exc.lines)
        code = 1
    except Exception as exc:
        lines = ["result=failed", "sdk=" + sdk_text(exc)]
        code = 1
    finally:
        if service is not None:
            try:
                service.disconnect()
                closed = True
            except Exception as exc:
                closed = False
                closure_error = sdk_text(exc)
        sys.stderr = old_err
        os.dup2(saved_fd, 2)
        os.close(saved_fd)
        logging.disable(previous_disable)
        private_note = _read_captured(captured)
        captured.close()
    if authenticated:
        lines = ["connection=verified"] + [line for line in lines if not line.startswith("connection=")]
    if closed is True:
        lines = ["session_closed=yes"] + [line for line in lines if not line.startswith("session_closed=")]
    elif closed is False:
        lines = ["session_closed=no"] + [line for line in lines if not line.startswith("session_closed=")]
        if closure_error:
            lines.append("closure_sdk=" + closure_error)
    return code, lines, creds, private_note


def permission_secret_values() -> list:
    if not _enabled():
        return []
    try:
        return secrets_of(load_credentials(config_path()))
    except DemoFailure:
        return []


def web_attempt(action: str) -> dict:
    """One HTTP click. The browser cannot choose the client, topic, or files."""
    if not _enabled():
        return {"result": "off", "action": action, "actor": "", "topic": "", "sentId": "", "receivedId": "", "receivedTopic": "", "sdk": "", "connectionVerified": False, "sessionClosed": None, "closureSdk": "", "sendReturned": False, "brokerAck": False}
    topic = WEB_ACTIONS.get(action)
    if topic is None:
        return {"result": "failed", "action": action, "actor": "", "topic": "", "sentId": "", "receivedId": "", "receivedTopic": "", "sdk": "unknown action", "connectionVerified": False, "sessionClosed": None, "closureSdk": "", "sendReturned": False, "brokerAck": False}
    if not _WEB_LOCK.acquire(blocking=False):
        return {"result": "busy", "action": action, "actor": "", "topic": topic, "sentId": "", "receivedId": "", "receivedTopic": "", "sdk": "another permissions click is still running", "connectionVerified": False, "sessionClosed": None, "closureSdk": "", "sendReturned": False, "brokerAck": False}
    try:
        try:
            creds = load_credentials(config_path())
        except DemoFailure as exc:
            return {
                "result": "failed",
                "action": action,
                "actor": "",
                "topic": topic,
                "sentId": "",
                "receivedId": "",
                "receivedTopic": "",
                "sdk": exc.lines[-1].split("=", 1)[-1],
                "connectionVerified": False,
                "sessionClosed": None,
                "closureSdk": "",
                "sendReturned": False,
                "brokerAck": False,
            }
        _code, lines, used, _note = broker_attempt(action, topic, creds["username"])
        return _public_result(action, creds["username"], topic, lines, used or creds)
    finally:
        _WEB_LOCK.release()


def run(argv: list) -> int:
    try:
        args = parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 2
    if _control(args.client) or _control(args.topic) or not args.topic:
        sys.stdout.write("result=failed\nsdk=client or topic is empty or has a control character\n")
        return 2
    code, lines, creds, private_note = broker_attempt(args.action, args.topic, args.client)
    emit(args.action, args.client, args.topic, lines, creds, private_note)
    return code


def main() -> None:
    sys.exit(run(sys.argv[1:]))


if __name__ == "__main__":
    main()
