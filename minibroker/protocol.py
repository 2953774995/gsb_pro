"""Length-prefixed text frame protocol used by minibroker.

Wire format (CRLF is the normal line terminator; LF is accepted when parsing)::

    *<number-of-arguments>\r\n
    $<byte-length>\r\n
    <exact-bytes>\r\n

The format is similar in spirit to RESP2 arrays/bulk strings, but intentionally
small.  Because every argument has an explicit byte length, payloads may contain
spaces, tabs, NUL bytes, CR, LF and arbitrary binary data.
"""

from __future__ import annotations

from typing import Any, BinaryIO, List, Optional, Sequence


DEFAULT_MAX_FRAME_SIZE = 1024 * 1024
_HARD_LINE_LIMIT = 64 * 1024 * 1024
_MAX_ARGUMENTS = 64


class ProtocolError(ValueError):
    """Raised when a peer sends a frame that cannot be parsed."""


class IncompleteFrameError(ProtocolError, EOFError):
    """Raised when a frame ends while more wire bytes are required."""


def _encode_value(value: Any) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8")
    if isinstance(value, int):
        return str(value).encode("ascii")
    raise TypeError("protocol values must be bytes, str or int")


def encode_frame(parts: Sequence[Any]) -> bytes:
    """Encode one array frame.

    Integers are accepted as a convenience; on the wire they are decimal text.
    """

    if not parts:
        raise ValueError("a frame must contain at least one part")
    if len(parts) > _MAX_ARGUMENTS:
        raise ValueError("frame contains too many parts")

    chunks: List[bytes] = [b"*" + str(len(parts)).encode("ascii") + b"\r\n"]
    for part in parts:
        raw = _encode_value(part)
        chunks.append(b"$" + str(len(raw)).encode("ascii") + b"\r\n")
        chunks.append(raw)
        chunks.append(b"\r\n")
    return b"".join(chunks)


def encode_command(command: str, *args: Any) -> bytes:
    """Encode a client command."""

    return encode_frame([command.encode("ascii"), *args])


def encode_ok(text: str = "OK") -> bytes:
    return b"+" + text.encode("ascii") + b"\r\n"


def encode_error(message: str) -> bytes:
    # Error replies are ASCII diagnostics.  Defensively remove line breaks so
    # one error can never be interpreted as several replies.
    safe = message.encode("ascii", "replace").replace(b"\r", b" ").replace(b"\n", b" ")
    return b"-ERR " + safe + b"\r\n"


def encode_integer(value: int) -> bytes:
    return b":" + str(value).encode("ascii") + b"\r\n"


def _read_line(
    reader: BinaryIO, frame_size: int, max_size: Optional[int]
) -> "tuple[bytes, int]":
    if max_size is None:
        limit = _HARD_LINE_LIMIT + 1
    else:
        limit = max_size - frame_size + 1
    if limit <= 0:
        raise ProtocolError("frame exceeds maximum size")

    # readline(limit) reads at most `limit` bytes without consuming the
    # terminator.  If even one byte is available but the limit is exhausted,
    # detect that as a size error rather than treating the following chunk as
    # EOF.
    line = reader.readline(limit)
    if not line:
        if max_size is not None:
            probe = reader.read(1)
            if probe:
                raise ProtocolError("frame exceeds maximum size")
        raise EOFError("connection closed")
    if not line.endswith(b"\n"):
        if max_size is not None and frame_size + len(line) > max_size:
            raise ProtocolError("frame exceeds maximum size")
        # A valid reader reaches EOF only after a complete final line.
        raise IncompleteFrameError("truncated line")

    frame_size += len(line)
    if max_size is not None and frame_size > max_size:
        raise ProtocolError("frame exceeds maximum size")

    if line.endswith(b"\r\n"):
        return line[:-2], frame_size
    return line[:-1], frame_size


def _read_bytes(
    reader: BinaryIO, size: int, frame_size: int, max_size: Optional[int]
) -> "tuple[bytes, int]":
    if size < 0:
        raise ProtocolError("negative bulk length")
    if max_size is not None and frame_size + size + 2 > max_size:
        # The +2 is for CRLF following the payload.
        raise ProtocolError("frame exceeds maximum size")

    chunks = []
    remaining = size
    while remaining:
        chunk = reader.read(remaining)
        if not chunk:
            raise EOFError("connection closed in the middle of a bulk value")
        chunks.append(chunk)
        remaining -= len(chunk)
        frame_size += len(chunk)
    return b"".join(chunks), frame_size


def read_frame(reader: BinaryIO, max_size: Optional[int] = DEFAULT_MAX_FRAME_SIZE):
    """Read one complete command/array frame.

    ``max_size`` counts every wire byte, including frame headers and CRLFs.
    ``None`` may be used by trusted local code (AOF replay) with a hard sanity
    limit on individual header lines.
    """

    frame_size = 0
    header, frame_size = _read_line(reader, frame_size, max_size)
    if not header.startswith(b"*"):
        raise ProtocolError("expected an array frame starting with '*'")
    try:
        count_text = header[1:]
        if not count_text.isdigit() or (len(count_text) > 1 and count_text.startswith(b"0")):
            raise ProtocolError("invalid array length")
        count = int(count_text)
    except ValueError as exc:
        raise ProtocolError("invalid array length") from exc
    if count < 1 or count > _MAX_ARGUMENTS:
        raise ProtocolError("invalid number of frame parts")

    values = []
    for _ in range(count):
        length_header, frame_size = _read_line(reader, frame_size, max_size)
        if not length_header.startswith(b"$"):
            raise ProtocolError("expected a bulk value starting with '$'")
        length_text = length_header[1:]
        if not length_text.isdigit() or (len(length_text) > 1 and length_text.startswith(b"0")):
            raise ProtocolError("invalid bulk length")
        try:
            length = int(length_text)
        except ValueError as exc:
            raise ProtocolError("invalid bulk length") from exc
        if length < 0:
            raise ProtocolError("negative bulk length")

        value, frame_size = _read_bytes(reader, length, frame_size, max_size)
        terminator, frame_size = _read_bytes(reader, 2, frame_size, max_size)
        if terminator != b"\r\n":
            raise ProtocolError("missing bulk-value CRLF terminator")
        values.append(value)

    return values


def read_value(reader: BinaryIO, max_size: Optional[int] = DEFAULT_MAX_FRAME_SIZE):
    """Read a server reply.

    Replies use simple ``+TEXT``, error ``-ERR ...``, integer ``:123`` and
    length-prefixed arrays/bulk values.  Arrays are returned as Python lists.
    """

    line, frame_size = _read_line(reader, 0, max_size)
    if not line:
        raise ProtocolError("empty reply")
    marker = line[0:1]
    body = line[1:]

    if marker == b"+":
        return body
    if marker == b"-":
        return body
    if marker == b":":
        try:
            return int(body)
        except ValueError as exc:
            raise ProtocolError("invalid integer reply") from exc

    if marker == b"$":
        try:
            length = int(body)
        except ValueError as exc:
            raise ProtocolError("invalid bulk length reply") from exc
        if length < 0:
            return None
        value, frame_size = _read_bytes(reader, length, len(line), max_size)
        terminator, _ = _read_bytes(reader, 2, frame_size, max_size)
        if terminator != b"\r\n":
            raise ProtocolError("missing bulk-value CRLF terminator")
        return value

    if marker == b"*":
        try:
            count = int(body)
        except ValueError as exc:
            raise ProtocolError("invalid array length reply") from exc
        if count < 0:
            return None
        # A tiny recursive parser is sufficient: all replies are shallow.
        return [read_value(reader, max_size) for _ in range(count)]

    raise ProtocolError("unknown reply type")


def encode_pub(sequence: int, topic: bytes, payload: bytes) -> bytes:
    return encode_frame([b"PUB", str(sequence).encode("ascii"), topic, payload])


def read_frame_from_bytes(data: bytes, max_size: Optional[int] = DEFAULT_MAX_FRAME_SIZE):
    import io

    return read_frame(io.BytesIO(data), max_size=max_size)


def read_value_from_bytes(data: bytes, max_size: Optional[int] = DEFAULT_MAX_FRAME_SIZE):
    import io

    return read_value(io.BytesIO(data), max_size=max_size)
