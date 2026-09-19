"""Wire protocol for minibroker.

The protocol is a small, human-readable, line-oriented text protocol with an
explicit length-prefixed body for binary payloads so that payloads may contain
arbitrary bytes (including spaces, tabs and ``\\n`` / ``\\r``).

Command grammar (one request per frame)::

    PING\n
    STATS\n
    FLUSH\n
    SHUTDOWN\n
    SUBSCRIBE <topic>\n
    UNSUBSCRIBE <topic>\n
    PUBLISH <topic> <length>\n
    <exactly <length> bytes of payload, no terminator required>

Replies (all terminated by ``\\n`` apart from bulk bodies)::

    +OK <text>\n            generic success (SUBSCRIBED / UNSUBSCRIBED / FLUSH)
    -ERR <text>\n           error reply
    +PONG\n                 reply to PING
    :<seq>\n                integer reply (PUBLISH -> assigned sequence)
    +STATS <n>\n            STATS reply, followed by ``n`` ``key=value`` lines
    MSG <topic> <seq> <length>\n<payload>
                            asynchronous push to a subscribed connection
    +BYE <reason>\n         server is shutting the connection down

Commands are case-insensitive; topics are case-sensitive.
"""

from __future__ import annotations

from typing import List, Optional

from .errors import ProtocolError

DEFAULT_PORT = 7379
DEFAULT_MAX_COMMAND_SIZE = 1024 * 1024  # 1 MiB, limit for a single command line
LINE_TERMINATOR = b"\n"
MAX_TOPIC_LENGTH = 128

KNOWN_COMMANDS = frozenset(
    {"PUBLISH", "SUBSCRIBE", "UNSUBSCRIBE", "PING", "STATS", "FLUSH", "SHUTDOWN"}
)


class Command:
    """A parsed client command.

    ``name`` is upper case. ``args`` holds the textual arguments. ``payload``
    is only populated for ``PUBLISH`` and carries raw bytes.
    """

    __slots__ = ("name", "args", "payload")

    def __init__(
        self,
        name: str,
        args: Optional[List[str]] = None,
        payload: Optional[bytes] = None,
    ) -> None:
        self.name = name
        self.args = args or []
        self.payload = payload

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Command(name=%r, args=%r, payload=%d bytes)" % (
            self.name,
            self.args,
            0 if self.payload is None else len(self.payload),
        )


def validate_topic(topic: str) -> None:
    """Validate a topic name.

    A topic must be non-empty, at most ``MAX_TOPIC_LENGTH`` characters long and
    contain no ASCII control characters or whitespace (the protocol is space
    and newline delimited). Wildcard suffixes (``*`` / ``/*``) are only legal
    on subscriptions, validated separately.
    """
    if not isinstance(topic, str):
        raise ProtocolError("topic must be a string")
    if not topic:
        raise ProtocolError("topic must not be empty")
    if len(topic) > MAX_TOPIC_LENGTH:
        raise ProtocolError(
            "topic must be at most %d characters" % MAX_TOPIC_LENGTH
        )
    for ch in topic:
        code = ord(ch)
        if code < 0x21 or code == 0x7F:
            raise ProtocolError(
                "topic must not contain control characters or whitespace"
            )


def validate_subscription_topic(topic: str) -> None:
    """Validate a topic used for (un)subscription, allowing wildcard suffix."""
    if topic.endswith("/*"):
        validate_topic(topic[:-2])
    elif topic == "*":
        return
    else:
        validate_topic(topic)


def topic_matches(subscription: str, topic: str) -> bool:
    """Return whether ``topic`` matches a (possibly wildcard) subscription."""
    if subscription == "*":
        return True
    if subscription.endswith("/*"):
        prefix = subscription[:-2]
        return topic == prefix or topic.startswith(prefix + "/")
    return subscription == topic


def _encode_publish(topic: str, payload: bytes) -> bytes:
    validate_topic(topic)
    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise TypeError("payload must be bytes")
    return b"PUBLISH %s %d\n" % (
        topic.encode("utf-8"),
        len(payload),
    ) + bytes(payload)


def encode_command(name: str, *args: str, payload: Optional[bytes] = None) -> bytes:
    """Serialize a client command (used by the SDK and tests)."""
    upper = name.upper()
    if upper == "PUBLISH":
        if len(args) != 1:
            raise ProtocolError("PUBLISH requires <topic>")
        return _encode_publish(args[0], payload or b"")
    if payload:
        raise ProtocolError("only PUBLISH carries a payload")
    if args:
        for arg in args:
            if any(ch in arg for ch in (" ", "\n", "\r", "\t")):
                raise ProtocolError("argument contains whitespace")
        return (upper + " " + " ".join(args) + "\n").encode("utf-8")
    return (upper + "\n").encode("utf-8")


def ok(text: str = "OK") -> bytes:
    return ("+%s\n" % text).encode("utf-8")


def error(text: str) -> bytes:
    if "\n" in text or "\r" in text:
        text = text.replace("\r", " ").replace("\n", " ")
    return ("-ERR %s\n" % text).encode("utf-8")


def pong() -> bytes:
    return b"+PONG\n"


def integer(value: int) -> bytes:
    return (":%d\n" % value).encode("utf-8")


def stats_reply(items) -> bytes:
    lines = ["%s=%s" % (key, value) for key, value in items]
    out = [("+STATS %d\n" % len(lines)).encode("utf-8")]
    out.extend(("%s\n" % line).encode("utf-8") for line in lines)
    return b"".join(out)


def message(topic: str, seq: int, payload: bytes) -> bytes:
    return b"MSG %s %d %d\n" % (
        topic.encode("utf-8"),
        seq,
        len(payload),
    ) + bytes(payload)


def bye(reason: str = "shutting down") -> bytes:
    return ("+BYE %s\n" % reason).encode("utf-8")


def parse_command_line(line: bytes) -> Command:
    """Parse a single command line (without trailing newline).

    The payload body of ``PUBLISH`` is *not* read here; the caller reads
    ``length`` bytes from the stream afterwards.
    """
    try:
        text = line.decode("utf-8")
    except UnicodeDecodeError:
        raise ProtocolError("command line must be valid UTF-8")
    parts = text.split(" ")
    name = parts[0].upper()
    if not name:
        raise ProtocolError("empty command")
    if name not in KNOWN_COMMANDS:
        raise ProtocolError("unknown command: %s" % parts[0])
    args = parts[1:]
    if any(part == "" for part in args):
        raise ProtocolError("empty argument in command")

    if name in {"PING", "STATS", "FLUSH", "SHUTDOWN"}:
        if args:
            raise ProtocolError("%s takes no arguments" % name)
        return Command(name)

    if name in {"SUBSCRIBE", "UNSUBSCRIBE"}:
        if len(args) != 1:
            raise ProtocolError("%s requires exactly <topic>" % name)
        validate_subscription_topic(args[0])
        return Command(name, args)

    # PUBLISH <topic> <length>
    if len(args) != 2:
        raise ProtocolError("PUBLISH requires <topic> <length>")
    validate_topic(args[0])
    length_str = args[1]
    if not length_str.isdigit():
        raise ProtocolError("PUBLISH length must be a non-negative integer")
    length = int(length_str)
    cmd = Command(name, [args[0]])
    cmd.payload = b"__PENDING__%d" % length  # placeholder carrying the length
    return cmd


class CommandReader:
    """Reads complete commands from a binary stream.

    Usage::

        reader = CommandReader(sock.makefile("rb"), max_command_size)
        cmd = reader.read_command()  # None on clean EOF
        if cmd.payload is pending: reader.read_payload(cmd)
    """

    def __init__(self, stream, max_command_size: int = DEFAULT_MAX_COMMAND_SIZE) -> None:
        self.stream = stream
        self.max_command_size = max_command_size

    def read_command(self) -> Optional[Command]:
        line = self.stream.readline()
        if line == b"":
            return None
        if not line.endswith(LINE_TERMINATOR):
            raise ProtocolError("connection closed mid-command")
        # Strip a single trailing \n (and an optional \r for friendliness).
        line = line[:-1]
        if line.endswith(b"\r"):
            line = line[:-1]
        if not line:
            raise ProtocolError("empty command line")
        if len(line) > self.max_command_size:
            raise ProtocolError(
                "command too large: limit is %d bytes" % self.max_command_size
            )
        return parse_command_line(line)

    def read_payload(self, cmd: Command) -> bytes:
        placeholder = cmd.payload
        if not (isinstance(placeholder, bytes) and placeholder.startswith(b"__PENDING__")):
            raise ProtocolError("command carries no pending payload")
        length = int(placeholder[len(b"__PENDING__") :])
        if length > self.max_command_size:
            raise ProtocolError(
                "payload too large: limit is %d bytes" % self.max_command_size
            )
        data = self.stream.read(length) if length else b""
        if len(data) != length:
            raise ProtocolError("connection closed mid-payload")
        cmd.payload = data
        return data


class ReplyReader:
    """Parses server replies for the client SDK."""

    def __init__(self, stream) -> None:
        self.stream = stream

    def read_reply(self):
        line = self.stream.readline()
        if line == b"":
            raise ProtocolError("connection closed by server")
        if not line.endswith(b"\n"):
            raise ProtocolError("truncated reply from server")
        line = line[:-1]
        if line.endswith(b"\r"):
            line = line[:-1]
        kind, _, rest = line.partition(b" ")
        kind_s = kind.decode("ascii", errors="replace")

        if kind_s == "MSG":
            topic_b, seq_b, len_b = rest.split(b" ")
            payload = self.stream.read(int(len_b))
            if len(payload) != int(len_b):
                raise ProtocolError("truncated message payload")
            return ("MSG", topic_b.decode("utf-8"), int(seq_b), payload)

        # integer reply ":<n>" has no separating space
        if line.startswith(b":"):
            return ("INT", int(line[1:]))

        if kind_s.startswith("+"):
            # Every success reply starts with '+': +PONG, +OK ..., +SUBSCRIBED
            # ..., +UNSUBSCRIBED ..., +BYE ...
            label = kind_s[1:]
            if label in {"OK", "SUBSCRIBED", "UNSUBSCRIBED", "FLUSHED"}:
                label = "OK"
            return (label, rest.decode("utf-8", errors="replace"))

        if kind_s == "-ERR":
            return ("ERR", rest.decode("utf-8", errors="replace"))

        if kind_s == "+STATS":
            count = int(rest)
            items = {}
            for _ in range(count):
                entry = self.stream.readline()
                if not entry.endswith(b"\n"):
                    raise ProtocolError("truncated STATS reply")
                key, _, value = entry[:-1].decode("utf-8").partition("=")
                items[key] = value
            return ("STATS", items)

        raise ProtocolError("unknown reply type: %r" % kind_s)
