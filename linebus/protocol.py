"""Linebus length-prefixed text protocol.

Wire format::

    COMMAND [argument ...] [payload-length]<LF>
    [<payload bytes>]

Only PUBLISH carries a payload.  Commands are plain ASCII text terminated by
LF (CR immediately before LF is accepted and removed).  Payloads are opaque
bytes and therefore may contain spaces, tabs, NUL bytes, CR and LF.

Examples::

    PING\n
    SUBSCRIBE quality/camera-1\n
    PUBLISH quality/camera-1 11\n
    hello world
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import BinaryIO, Dict, List, Optional, Tuple


DEFAULT_MAX_COMMAND_SIZE = 1024 * 1024  # one MiB, including header and payload


class ProtocolError(Exception):
    """A malformed protocol frame was received."""


class CommandTooLargeError(ProtocolError):
    """A command exceeded the negotiated maximum frame size."""


@dataclass(frozen=True)
class Frame:
    """A decoded command frame.

    ``parts`` contains the textual header tokens.  ``payload`` is the exact
    binary payload and is empty for payload-less commands.
    """

    parts: Tuple[str, ...]
    payload: bytes = b""

    @property
    def command(self) -> str:
        return self.parts[0].upper() if self.parts else ""


def _read_header_line(stream: BinaryIO, max_command_size: int) -> bytes:
    """Read one LF-terminated header, enforcing a preliminary size bound."""
    data = bytearray()
    while True:
        ch = stream.read(1)
        if not ch:
            if data:
                raise ProtocolError("unexpected EOF while reading command header")
            return b""
        if ch == b"\n":
            if data.endswith(b"\r"):
                data.pop()
            if len(data) + 1 > max_command_size:
                raise CommandTooLargeError("command is too large")
            return bytes(data)
        if len(data) >= max_command_size:
            # Consume a bounded remainder so a well-behaved peer can receive
            # the error instead of desynchronising every following command.
            extra = 0
            while ch != b"\n":
                ch = stream.read(1)
                if not ch:
                    break
                extra += 1
                if extra > 65536:
                    raise CommandTooLargeError("command header is too large")
            raise CommandTooLargeError("command is too large")
        data.extend(ch)


def _read_exact(stream: BinaryIO, size: int) -> bytes:
    chunks: List[bytes] = []
    remaining = size
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            raise ProtocolError("unexpected EOF while reading payload")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_frame(stream: BinaryIO, max_command_size: int = DEFAULT_MAX_COMMAND_SIZE) -> Optional[Frame]:
    """Read one complete frame.

    Returns ``None`` on a clean EOF before a new command.  The parser raises
    :class:`ProtocolError` for malformed input and :class:`CommandTooLargeError`
    after consuming an over-large frame where its length is known.
    """
    if max_command_size <= 0:
        raise ValueError("max_command_size must be positive")
    header = _read_header_line(stream, max_command_size)
    if not header:
        return None
    try:
        header_text = header.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ProtocolError("command header must be ASCII") from exc

    parts = header_text.split(" ")
    if any(part == "" for part in parts):
        raise ProtocolError("command header contains an empty token")
    if not parts:
        raise ProtocolError("empty command")

    payload = b""
    length_field: str
    command_name = parts[0].upper()
    if len(parts) == 3 and command_name == "PUBLISH":
        length_field = parts[2]
    elif len(parts) == 3 and command_name == "OK" and parts[1] == "STATS":
        length_field = parts[2]
    elif len(parts) == 4 and command_name == "EVENT":
        length_field = parts[3]
    elif len(parts) > 3 and command_name in {"ERR", "OK"}:
        # Replies are human-readable text and may contain spaces.
        return Frame(tuple(parts), b"")
    elif len(parts) > 3:
        # Only PUBLISH uses a payload, and it has exactly three header tokens.
        raise ProtocolError("too many header fields")
    else:
        # Non-data commands are validated by the command dispatcher. This lets
        # it return ERR for an unknown command without interpreting the third
        # token as an opaque payload length.
        return Frame(tuple(parts), b"")

    try:
        length = int(length_field, 10)
    except ValueError as exc:
        raise ProtocolError("payload length must be a non-negative integer") from exc
    if length < 0:
        raise ProtocolError("payload length must be a non-negative integer")
    if len(header) + 1 + length > max_command_size:
        # Drain the advertised payload so the connection remains at a frame
        # boundary while the error reply is being written.
        _read_exact(stream, length)
        raise CommandTooLargeError(
            f"command size exceeds limit of {max_command_size} bytes"
        )
    payload = _read_exact(stream, length)
    return Frame(tuple(parts), payload)


def encode_header(*parts: object) -> bytes:
    return (" ".join(str(part) for part in parts) + "\n").encode("ascii")


def encode_publish(topic: str, payload: bytes) -> bytes:
    if not isinstance(payload, (bytes, bytearray)):
        raise TypeError("payload must be bytes")
    return encode_header("PUBLISH", topic, len(payload)) + bytes(payload)


def encode_simple(command: str) -> bytes:
    command = command.upper()
    if command not in {"PING", "STATS", "FLUSH", "SHUTDOWN"}:
        raise ValueError(f"{command!r} requires topic arguments")
    return encode_header(command)


def encode_subscribe(topic: str) -> bytes:
    return encode_header("SUBSCRIBE", topic)


def encode_unsubscribe(topic: str) -> bytes:
    return encode_header("UNSUBSCRIBE", topic)


def encode_event(sequence: int, topic: str, payload: bytes) -> bytes:
    if not isinstance(payload, (bytes, bytearray)):
        raise TypeError("payload must be bytes")
    return encode_header("EVENT", sequence, topic, len(payload)) + bytes(payload)


def encode_error(message: str) -> bytes:
    # Error messages are one line. Payload bytes never appear in an ERR line.
    message = message.replace("\r", " ").replace("\n", " ")
    return encode_header("ERR", message)


def encode_ok(message: str = "OK") -> bytes:
    return encode_header("OK", message)


def validate_topic(topic: object, *, allow_wildcard: bool = False) -> str:
    """Validate an ordinary topic or a subscription pattern."""
    if not isinstance(topic, str):
        raise ProtocolError("topic must be a string")
    if not topic:
        raise ProtocolError("topic must not be empty")
    if len(topic.encode("utf-8")) > 255:
        raise ProtocolError("topic must be at most 255 bytes")
    if any((ord(ch) < 32 or ord(ch) == 127 or ch.isspace()) for ch in topic):
        raise ProtocolError("topic must not contain control characters or whitespace")
    if "*" in topic:
        if not allow_wildcard:
            raise ProtocolError("'*' is reserved for subscription patterns")
        if not topic.endswith("/*"):
            raise ProtocolError("wildcard pattern must end with '/*'")
        prefix = topic[:-2]
        if not prefix or "*" in prefix or not all(segment for segment in prefix.split("/")):
            raise ProtocolError("invalid wildcard topic pattern")
    return topic


def topic_matches(pattern: str, topic: str) -> bool:
    """Return whether a terminal-wildcard subscription matches a topic."""
    if pattern == topic:
        return True
    if pattern.endswith("/*"):
        prefix = pattern[:-2]
        return topic == prefix or topic.startswith(prefix + "/")
    return False


def parse_event_frame(frame: Frame) -> Tuple[int, str, bytes]:
    """Parse an EVENT frame used by clients."""
    if frame.command != "EVENT" or len(frame.parts) != 4:
        raise ProtocolError("expected EVENT <seq> <topic> <length>")
    try:
        sequence = int(frame.parts[1], 10)
        length = int(frame.parts[3], 10)
    except ValueError as exc:
        raise ProtocolError("invalid EVENT frame") from exc
    if sequence < 0 or length != len(frame.payload):
        raise ProtocolError("invalid EVENT frame")
    topic = frame.parts[2]
    validate_topic(topic)
    return sequence, topic, frame.payload
