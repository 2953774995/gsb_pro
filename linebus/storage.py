"""In-memory event records and topic validation/matching helpers."""

from __future__ import annotations

from dataclasses import dataclass
import unicodedata


@dataclass(frozen=True)
class Event:
    sequence: int
    topic: str
    payload: bytes


def validate_topic(topic: object, *, allow_wildcard: bool = False) -> str:
    """Validate a topic or subscription pattern.

    Topics are UTF-8 text. They must be non-empty and must not contain ASCII
    control characters. Leading/trailing whitespace is rejected because it is
    almost always an operational mistake, while internal spaces are permitted.
    A subscription may end in ``/*`` for one-segment wildcard matching.
    """

    if not isinstance(topic, str):
        raise ValueError("topic must be a UTF-8 string")
    if not topic:
        raise ValueError("topic must not be empty")
    if topic != topic.strip():
        raise ValueError("topic must not have leading or trailing whitespace")
    if "\x00" in topic:
        raise ValueError("topic must not contain control characters")
    for ch in topic:
        cat = unicodedata.category(ch)
        if cat in {"Cc", "Cf"}:
            raise ValueError("topic must not contain control characters")

    if allow_wildcard:
        if "*" in topic:
            if not topic.endswith("/*") or topic == "/*":
                raise ValueError("wildcard pattern must end with a non-empty '/*' suffix")
            base = topic[:-2]
            validate_topic(base)
            return topic
    elif "*" in topic:
        raise ValueError("'*' is only supported as a trailing subscription wildcard")
    return topic


def topic_matches(pattern: str, topic: str) -> bool:
    """Return whether an exact topic matches a subscription pattern."""

    if pattern == topic:
        return True
    if pattern.endswith("/*"):
        prefix = pattern[:-1]  # Keep the slash: "a/*" -> "a/"
        if not topic.startswith(prefix):
            return False
        suffix = topic[len(prefix) :]
        return bool(suffix) and "/" not in suffix
    return False
