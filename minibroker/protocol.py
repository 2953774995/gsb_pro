"""Wire protocol for minibroker.

Frame format (all header lines are UTF-8, terminated by "\n")::

    <COMMAND> [arg ...] [<payload-length>]\n[<payload bytes>\n]

Commands that carry a payload (PUBLISH, MSG) put the payload length as
the last header token; exactly <payload-length> bytes follow, then a
single "\n" terminator.  This lets payloads contain arbitrary bytes,
including spaces, tabs and newlines.

Server replies are single-line frames:

    +OK [arg ...]\n        success
    +PONG\n                answer to PING
    +STATS k=v ...\n       answer to STATS
    +BYE <reason>\n        server is shutting down
    -ERR <message>\n       any error

Asynchronous message delivery uses a MSG frame:

    MSG <seq> <topic> <payload-length>\n<payload>\n
"""

DEFAULT_MAX_COMMAND = 1024 * 1024  # 1 MB

PAYLOAD_COMMANDS = frozenset({"PUBLISH", "MSG"})


class ProtocolError(Exception):
    """Malformed frame; the stream can no longer be trusted."""


class CommandTooLarge(ProtocolError):
    """Frame exceeds the configured maximum command size."""


def encode_command(command, args=(), payload=None):
    """Encode a command (or reply) into bytes ready to send."""
    parts = [command] + [str(arg) for arg in args]
    if payload is None:
        return (" ".join(parts) + "\n").encode("utf-8")
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    parts.append(str(len(payload)))
    header = " ".join(parts).encode("utf-8")
    return header + b"\n" + payload + b"\n"


def encode_ok(*args):
    return encode_command("+OK", args)


def encode_error(message):
    return encode_command("-ERR", [message])


def encode_message(seq, topic, payload):
    return encode_command("MSG", [seq, topic], payload)


def _read_exactly(stream, count):
    data = stream.read(count)
    if data is None or len(data) < count:
        raise EOFError("connection closed mid-frame")
    return data


def read_frame(stream, max_command=DEFAULT_MAX_COMMAND):
    """Read one frame from a binary stream.

    Returns ``(tokens, payload)`` where ``tokens`` is the list of header
    tokens and ``payload`` is bytes for payload commands else ``None``.

    Raises EOFError on clean/unclean disconnect and ProtocolError (or its
    subclass CommandTooLarge) on malformed input.
    """
    header = stream.readline(max_command + 2)
    if not header:
        raise EOFError("connection closed")
    if len(header) > max_command + 1 or not header.endswith(b"\n"):
        raise CommandTooLarge("command exceeds %d bytes" % max_command)
    header = header[:-1]
    if header.endswith(b"\r"):
        header = header[:-1]
    if not header:
        raise ProtocolError("empty command line")
    try:
        text = header.decode("utf-8")
    except UnicodeDecodeError:
        raise ProtocolError("header is not valid UTF-8")
    tokens = text.split(" ")
    command = tokens[0].upper()
    payload = None
    if command in PAYLOAD_COMMANDS:
        if len(tokens) < 2:
            raise ProtocolError("missing payload length")
        try:
            length = int(tokens[-1])
        except ValueError:
            raise ProtocolError("invalid payload length: %r" % tokens[-1])
        if length < 0:
            raise ProtocolError("negative payload length")
        if len(header) + 1 + length > max_command:
            raise CommandTooLarge("command exceeds %d bytes" % max_command)
        payload = _read_exactly(stream, length)
        if _read_exactly(stream, 1) != b"\n":
            raise ProtocolError("payload not terminated by newline")
    return tokens, payload


def is_valid_topic(topic):
    """Topics: non-empty, no whitespace/control chars, no wildcards."""
    if not topic:
        return False
    for char in topic:
        code = ord(char)
        if code < 33 or code == 127 or char == "*":
            return False
    return True


def is_valid_pattern(pattern):
    """Subscription pattern: a topic, or ``<topic>/*`` wildcard."""
    if pattern.endswith("/*"):
        return is_valid_topic(pattern[:-2])
    return is_valid_topic(pattern)
