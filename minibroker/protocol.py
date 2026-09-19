"""Wire protocol definition and (de)serialization helpers for minibroker.

The protocol is a simple text protocol.  Every *header* is a single line of
ASCII/UTF-8 text terminated by ``\\n``.  Payloads are length-prefixed raw
bytes, so they may contain arbitrary binary data (spaces, tabs, newlines,
NUL bytes, ...).

Client -> Server frames::

    PUBLISH <topic> <payload_len>\n<payload bytes>
    SUBSCRIBE <pattern>\n
    UNSUBSCRIBE <pattern>\n
    PING\n
    STATS\n
    FLUSH\n
    SHUTDOWN\n

Server -> Client frames::

    OK [text]\n
    ERR <message>\n
    PONG\n
    MSG <seq> <topic> <payload_len>\n<payload bytes>
    STATS <payload_len>\n<json bytes>
    BYE <reason>\n

A single command (header line + payload) may not exceed
:data:`DEFAULT_MAX_COMMAND_SIZE` bytes (1 MiB) unless configured otherwise.
"""

from __future__ import annotations

NEWLINE = b"\n"
DEFAULT_MAX_COMMAND_SIZE = 1024 * 1024  # 1 MiB
MAX_TOPIC_LEN = 512
MAX_HEADER_LEN = 4096


class ProtocolError(Exception):
    """Raised when a peer sends something that violates the wire protocol."""


# ---------------------------------------------------------------------------
# low level readers
# ---------------------------------------------------------------------------

def read_line(rfile, limit: int) -> bytes:
    """Read one ``\\n`` terminated line (without the newline) from *rfile*.

    Raises :class:`EOFError` when the connection is closed and
    :class:`ProtocolError` when the line exceeds *limit* bytes (the rest of
    the offending line is consumed so the stream stays in sync).
    """
    line = rfile.readline(limit + 2)
    if not line:
        raise EOFError("connection closed")
    if line.endswith(NEWLINE) and len(line) <= limit + 1:
        return line[:-1]
    # Line is too long: discard the remainder so we can resynchronise.
    if not line.endswith(NEWLINE):
        while True:
            chunk = rfile.readline(65536)
            if not chunk:
                raise EOFError("connection closed")
            if chunk.endswith(NEWLINE):
                break
    raise ProtocolError("command too large")


def read_exact(rfile, n: int) -> bytes:
    """Read exactly *n* bytes or raise :class:`EOFError`."""
    data = rfile.read(n)
    if data is None or len(data) < n:
        raise EOFError("connection closed while reading payload")
    return data


# ---------------------------------------------------------------------------
# topic / pattern validation and matching
# ---------------------------------------------------------------------------

def _check_chars(value: str) -> bool:
    for ch in value:
        o = ord(ch)
        if o <= 0x20 or o == 0x7F:
            return False
    return True


def validate_topic(topic: str) -> None:
    """Validate a publish topic.  Raises :class:`ValueError` if invalid."""
    if not topic:
        raise ValueError("topic must not be empty")
    if len(topic) > MAX_TOPIC_LEN:
        raise ValueError("topic too long (max %d chars)" % MAX_TOPIC_LEN)
    if "*" in topic:
        raise ValueError("topic must not contain '*'")
    if not _check_chars(topic):
        raise ValueError("topic must not contain whitespace or control characters")


def validate_pattern(pattern: str) -> None:
    """Validate a subscription pattern (``topic`` or ``topic/*``)."""
    if pattern.endswith("/*"):
        base = pattern[:-2]
        if not base:
            raise ValueError("wildcard pattern must have a non-empty prefix")
        validate_topic(base)
    else:
        validate_topic(pattern)


def pattern_matches(pattern: str, topic: str) -> bool:
    """Return True if subscription *pattern* matches *topic*.

    ``foo/*`` matches any topic that starts with ``foo/`` and has a
    non-empty remainder (e.g. ``foo/bar`` and ``foo/bar/baz``).
    Any other pattern only matches the identical topic.
    """
    if pattern.endswith("/*"):
        prefix = pattern[:-1]  # keeps the trailing '/'
        return topic.startswith(prefix) and len(topic) > len(prefix)
    return pattern == topic


# ---------------------------------------------------------------------------
# frame encoders
# ---------------------------------------------------------------------------

def encode_publish(topic: str, payload: bytes) -> bytes:
    return (
        b"PUBLISH " + topic.encode("utf-8") + b" "
        + str(len(payload)).encode("ascii") + NEWLINE + payload
    )


def encode_simple(command: str, *args: str) -> bytes:
    parts = [command.encode("ascii")]
    parts += [a.encode("utf-8") for a in args]
    return b" ".join(parts) + NEWLINE


def encode_msg(seq: int, topic: str, payload: bytes) -> bytes:
    return (
        b"MSG " + str(seq).encode("ascii") + b" " + topic.encode("utf-8")
        + b" " + str(len(payload)).encode("ascii") + NEWLINE + payload
    )


def encode_stats(payload: bytes) -> bytes:
    return b"STATS " + str(len(payload)).encode("ascii") + NEWLINE + payload


def encode_ok(text: str = "") -> bytes:
    return b"OK " + text.encode("utf-8") + NEWLINE if text else b"OK\n"


def encode_err(message: str) -> bytes:
    return b"ERR " + message.encode("utf-8", "replace") + NEWLINE


# ---------------------------------------------------------------------------
# frame parsers
# ---------------------------------------------------------------------------

def parse_command_line(line: bytes):
    """Split a command header line into tokens (list of bytes)."""
    return line.split(b" ")


def parse_msg_header(line: bytes):
    """Parse a ``MSG <seq> <topic> <len>`` header. Returns (seq, topic, length)."""
    parts = line.split(b" ")
    if len(parts) != 4 or parts[0] != b"MSG":
        raise ProtocolError("malformed MSG header")
    try:
        seq = int(parts[1])
        length = int(parts[3])
        topic = parts[2].decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise ProtocolError("malformed MSG header: %s" % exc)
    if length < 0:
        raise ProtocolError("negative payload length")
    return seq, topic, length
