"""Solace SMF topic-subscription matching.

`*` matches one level. `>` matches one or more levels and must be last.
This is the rule the unit tests lock. The broker integration test checks
the same cases on a real broker.
"""

from __future__ import annotations

from solace_demo.catalog import LAUNCH_SUBSCRIPTION, OBJECT_SUBSCRIPTION, TOPIC_BOTH
from solace_demo.config import ConfigError


class TopicSyntaxError(ValueError):
    """A topic or subscription uses a level this demo does not send."""


def levels(value: str) -> tuple[str, ...]:
    if not value or value.startswith("/") or value.endswith("/") or "//" in value:
        raise TopicSyntaxError(f"empty topic level in {value!r}")
    return tuple(value.split("/"))


def subscription_matches(subscription: str, topic: str) -> bool:
    """Return True when a published topic matches a subscription."""
    return _match(levels(subscription), levels(topic))


def _match(sub: tuple[str, ...], topic: tuple[str, ...]) -> bool:
    if not sub:
        return not topic
    token = sub[0]
    if token == ">":
        if len(sub) != 1:
            raise TopicSyntaxError("'>' is only valid as the last subscription level")
        return len(topic) >= 1
    if not topic:
        return False
    if token != "*" and token != topic[0]:
        return False
    return _match(sub[1:], topic[1:])


def acl_decision(topic: str, default: str, exceptions: tuple[str, ...]) -> str:
    """Apply a Solace-style default plus exceptions.

    A topic that matches an exception gets the opposite of `default`.
    `default` is whatever this lab configured. It is not the broker's
    built-in profile.
    """
    if default not in ("allow", "disallow"):
        raise ValueError(f"unsupported ACL default {default!r}")
    matched = any(subscription_matches(exception, topic) for exception in exceptions)
    if matched:
        return "disallow" if default == "allow" else "allow"
    return default


DIRECT_ROOT = "ssa/unclass"
DIRECT_BRIDGE_SUBSCRIPTION = "ssa/>"


def guaranteed_topic(direct_topic: str, prefix: str) -> str:
    """Keep the direct tail and replace only the ssa/unclass root."""
    root = DIRECT_ROOT + "/"
    if not direct_topic.startswith(root):
        raise ValueError("direct topic is outside ssa/unclass")
    return prefix + direct_topic[len(DIRECT_ROOT) :]


def _disallowed_prefix_char(ch: str) -> bool:
    code = ord(ch)
    return ch.isspace() or code < 32 or code == 127


def validate_guaranteed_prefix(prefix: str) -> str:
    """Reject a prefix the existing direct bridge subscription would carry."""
    if (
        not prefix
        or prefix.startswith("/")
        or prefix.endswith("/")
        or "//" in prefix
        or any(ch in prefix for ch in "*#>")
        or any(_disallowed_prefix_char(ch) for ch in prefix)
    ):
        raise ConfigError(
            "SOLACE_GUARANTEED_TOPIC_PREFIX must be two topic levels, with no whitespace, control character, wildcard, or slash at either end."
        )
    levels = prefix.split("/")
    if len(levels) != 2 or levels[0] == "ssa":
        raise ConfigError(
            "SOLACE_GUARANTEED_TOPIC_PREFIX must be two topic levels and must not start with ssa."
        )
    sample = guaranteed_topic(TOPIC_BOTH, prefix)
    heartbeat = guaranteed_topic("ssa/unclass/ground1/status/25544/heartbeat", prefix)
    if (
        subscription_matches(DIRECT_BRIDGE_SUBSCRIPTION, sample)
        or subscription_matches(LAUNCH_SUBSCRIPTION, sample)
        or subscription_matches(OBJECT_SUBSCRIPTION, heartbeat)
    ):
        raise ConfigError(
            "SOLACE_GUARANTEED_TOPIC_PREFIX must be two topic levels and must not start with ssa."
        )
    return prefix
