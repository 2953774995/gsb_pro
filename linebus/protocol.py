"""Linebus text protocol.

Wire format (all frames are terminated by LF)::

    PUBLISH <topic> <decimal-payload-length>\n
    <payload-bytes>\n
    SUBSCRIBE <topic>\n
    UNSUBSCRIBE <topic>\n
    PING\n
    STATS\n
    FLUSH\n
    SHUTDOWN\n

The server asynchronously pushes events using::

    EVENT <seq> <topic> <decimal-payload-length>\n
    <payload-bytes>\n

Keeping payloads as raw bytes followed by LF allows them to contain spaces,
tabs, NUL bytes, embedded newlines, and other arbitrary data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


DEFAULT_MAX_COMMAND_SIZE = 1024 * 1024
LF = b"\n"
SIMPLE_COMMANDS = frozenset({"PING", "STATS", "FLUSH", "SHUTDOWN"})
ARG_COMMANDS = frozenset({"SUBSCRIBE", "UNSUBSCRIBE"})
PUBLISH = "PUBLISH"
EVENT = "EVENT"


class ProtocolError(Exception):
    """Base class for protocol violations."""


class ProtocolParseError(ProtocolError):
    """A malformed frame was encountered. The connection must be closed."""


class CommandTooLargeError(ProtocolParseError):
    """The advertised or received frame exceeds the configured size."""


@dataclass(frozen=True)
class Message:
    """A parsed request or server-pushed event."""

    command: str
    topic: Optional[str] = None
    payload: bytes = b""
    sequence: int = 0

    @property
    def is_event(self) -> bool:
        return self.command == EVENT


class ProtocolParser:
    """Incremental parser for one TCP stream.

    Feed bytes as they arrive; complete :class:`Message` objects are returned.
    Any parse exception is fatal because the receiver cannot safely locate the
    next frame boundary after malformed data.
    """

    def __init__(self, max_command_size: int = DEFAULT_MAX_COMMAND_SIZE):
        if max_command_size < 1:
            raise ValueError("max_command_size must be positive")
        self.max_command_size = max_command_size
        self._buf = bytearray()
        self._state = "header"
        self._command: Optional[str] = None
        self._topic: Optional[str] = None
        self._sequence = 0
        self._payload_left = 0

    def feed(self, data: bytes) -> list[Message]:
        self._buf.extend(data)
        messages: list[Message] = []
        while self._step(messages):
            pass
        return messages

    def _step(self, messages: list[Message]) -> bool:
        if self._state == "payload":
            return self._consume_payload(messages)
        return self._consume_header(messages)

    def _consume_header(self, messages: list[Message]) -> bool:
        if len(self._buf) > self.max_command_size:
            raise CommandTooLargeError(
                f"command exceeds maximum size of {self.max_command_size} bytes"
            )
        idx = self._buf.find(LF)
        if idx < 0:
            return False
        header = bytes(self._buf[:idx])
        del self._buf[: idx + 1]
        message = self._parse_header(header)
        if message is not None:
            messages.append(message)
            # Ready for the next frame.
            self._state = "header"
        return bool(self._buf) or self._state == "payload"

    def _parse_header(self, header: bytes) -> Optional[Message]:
        sp = header.find(b" ")
        if sp < 0:
            command_b, rest = header, b""
        else:
            command_b, rest = header[:sp], header[sp + 1 :]
        try:
            requested = command_b.decode("ascii")
        except UnicodeDecodeError as exc:
            raise ProtocolParseError("invalid command token") from exc
        command = requested.upper()

        if command in SIMPLE_COMMANDS:
            if rest:
                raise ProtocolParseError(f"{command} accepts no arguments")
            return Message(command=command)
        if command in ARG_COMMANDS:
            # Empty is retained as a value so the broker returns the standard
            # invalid-topic error; malformed binary/UTF-8 is still fatal.
            topic = "" if not rest else self._decode_topic(rest)
            return Message(command=command, topic=topic)
        if command == PUBLISH:
            self._begin_length_command(PUBLISH, rest)
            return None
        if command == EVENT:
            self._begin_event(rest)
            return None
        # Unknown line-based commands can safely skip to the next line; keep
        # the connection alive and let the broker produce the standard ERR.
        return Message(command=requested, topic=rest.decode("utf-8", errors="replace") if rest else None)

    def _begin_length_command(self, command: str, rest: bytes) -> None:
        sp = rest.rfind(b" ")
        if sp < 0:
            # A complete line with missing arguments is an application-level
            # command error; the connection can safely continue.
            return Message(command=command, topic=None)
        topic_raw = rest[:sp]
        topic = "" if not topic_raw else self._decode_topic(topic_raw)
        length = self._decode_length(rest[sp + 1 :], f"{command} payload length")
        self._command = command
        self._topic = topic
        self._sequence = 0
        self._payload_left = length
        self._state = "payload"

    def _begin_event(self, rest: bytes) -> None:
        first = rest.find(b" ")
        last = rest.rfind(b" ")
        if first <= 0 or last <= first:
            raise ProtocolParseError("EVENT requires <seq> <topic> <length>")
        sequence = self._decode_nonnegative_int(rest[:first], "EVENT sequence", positive=True)
        topic = self._decode_topic(rest[first + 1 : last])
        length = self._decode_length(rest[last + 1 :], "EVENT payload length")
        self._command = EVENT
        self._topic = topic
        self._sequence = sequence
        self._payload_left = length
        self._state = "payload"

    @staticmethod
    def _decode_topic(raw: bytes) -> str:
        if not raw:
            raise ProtocolParseError("topic must not be empty")
        try:
            return raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise ProtocolParseError("topic must be valid UTF-8") from exc

    def _decode_length(self, raw: bytes, label: str) -> int:
        length = self._decode_nonnegative_int(raw, label, positive=False)
        if length > self.max_command_size:
            raise CommandTooLargeError(
                f"payload exceeds maximum size of {self.max_command_size} bytes"
            )
        return length

    @staticmethod
    def _decode_nonnegative_int(raw: bytes, label: str, *, positive: bool) -> int:
        try:
            value = int(raw.decode("ascii"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise ProtocolParseError(f"invalid {label}") from exc
        if positive:
            if value < 1:
                raise ProtocolParseError(f"{label} must be positive")
        elif value < 0:
            raise ProtocolParseError(f"{label} cannot be negative")
        return value

    def _consume_payload(self, messages: list[Message]) -> bool:
        needed = self._payload_left + 1
        if len(self._buf) < needed:
            if len(self._buf) > self.max_command_size:
                raise CommandTooLargeError("payload exceeds maximum command size")
            return False
        end = self._payload_left
        if self._buf[end] != 0x0A:
            raise ProtocolParseError("payload must be terminated by LF")
        payload = bytes(self._buf[:end])
        del self._buf[:needed]
        message = Message(
            command=self._command or "",
            topic=self._topic,
            payload=payload,
            sequence=self._sequence,
        )
        self._command = None
        self._topic = None
        self._sequence = 0
        self._payload_left = 0
        self._state = "header"
        messages.append(message)
        return bool(self._buf)


def _topic_bytes(topic: str) -> bytes:
    if not isinstance(topic, str):
        raise TypeError("topic must be str")
    return topic.encode("utf-8")


def _payload_bytes(payload) -> bytes:
    if payload is None:
        return b""
    if isinstance(payload, str):
        return payload.encode("utf-8")
    if isinstance(payload, (bytes, bytearray, memoryview)):
        return bytes(payload)
    raise TypeError("payload must be bytes, str, or None")


def encode_publish(topic: str, payload: bytes | str | bytearray | memoryview | None = None) -> bytes:
    raw_topic = _topic_bytes(topic)
    raw_payload = _payload_bytes(payload)
    return b"PUBLISH " + raw_topic + b" " + str(len(raw_payload)).encode("ascii") + LF + raw_payload + LF


def encode_command(command: str, topic: str | None = None) -> bytes:
    upper = command.upper()
    if upper == PUBLISH:
        raise ValueError("use encode_publish for PUBLISH")
    if upper in SIMPLE_COMMANDS:
        if topic is not None:
            raise ProtocolError(f"{upper} accepts no arguments")
        return upper.encode("ascii") + LF
    if upper in ARG_COMMANDS:
        if topic is None:
            raise ProtocolError(f"{upper} requires a topic")
        return upper.encode("ascii") + b" " + _topic_bytes(topic) + LF
    raise ProtocolError(f"cannot encode unknown command: {command}")


def encode_event(sequence: int, topic: str, payload: bytes | str | bytearray | memoryview | None) -> bytes:
    if sequence < 1:
        raise ValueError("sequence must be positive")
    raw_payload = _payload_bytes(payload)
    return (
        b"EVENT "
        + str(sequence).encode("ascii")
        + b" "
        + _topic_bytes(topic)
        + b" "
        + str(len(raw_payload)).encode("ascii")
        + LF
        + raw_payload
        + LF
    )


def encode_ok(message: str = "OK") -> bytes:
    if message == "OK":
        return b"OK\n"
    return b"OK " + message.encode("utf-8") + LF


def encode_error(message: str) -> bytes:
    text = message.encode("utf-8", errors="replace").replace(b"\r", b" ").replace(b"\n", b" ")
    return b"ERR " + text + LF


def encode_bye(message: str = "server shutting down") -> bytes:
    return b"BYE " + message.encode("utf-8").replace(b"\n", b" ") + LF


def encode_stats(stats: dict) -> bytes:
    import json

    data = json.dumps(stats, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return b"OK " + data + LF
