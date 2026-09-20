"""Topic validation and wildcard matching helpers."""

from __future__ import annotations

from typing import Iterator


class InvalidTopicError(ValueError):
    pass


def _has_control_char(value: bytes) -> bool:
    return any(byte < 32 or byte == 127 for byte in value)


def validate_topic(topic: bytes, *, allow_wildcard: bool = False) -> None:
    if not isinstance(topic, bytes):
        raise InvalidTopicError("topic must be bytes")
    if not topic:
        raise InvalidTopicError("topic must not be empty")
    if _has_control_char(topic):
        raise InvalidTopicError("topic must not contain control characters")

    if b"*" not in topic:
        return

    if not allow_wildcard:
        raise InvalidTopicError("literal topic must not contain '*'")
    if topic == b"*":
        return
    if not topic.endswith(b"/*"):
        raise InvalidTopicError("wildcard topic must end with '/*' or be '*'")

    prefix = topic[:-2]
    if not prefix or _has_control_char(prefix) or b"*" in prefix:
        raise InvalidTopicError("invalid wildcard prefix")


def is_wildcard(topic: bytes) -> bool:
    return topic == b"*" or topic.endswith(b"/*")


def wildcard_prefix(topic: bytes) -> bytes:
    """Return the literal prefix for a validated ``prefix/*`` pattern."""

    return b"" if topic == b"*" else topic[:-2]


def prefixes_for_literal(topic: bytes) -> Iterator[bytes]:
    """Yield wildcard prefixes that can match a hierarchical literal topic.

    For ``a/b/c`` this yields ``a`` and ``a/b``; therefore subscriptions for
    both ``a/*`` and ``a/b/*`` match.
    """

    parts = topic.split(b"/")
    for index in range(1, len(parts)):
        yield b"/".join(parts[:index])


def topic_matches_prefix(literal_topic: bytes, prefix: bytes) -> bool:
    if not literal_topic.startswith(prefix + b"/"):
        return False
    remainder = literal_topic[len(prefix) + 1 :]
    return bool(remainder) and not remainder.startswith(b"/") and b"//" not in literal_topic
