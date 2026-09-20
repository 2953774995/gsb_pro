"""Append-only persistence for Linebus events.

Record format, one record per event::

    P <sequence> <topic-byte-length> <payload-length>\n
    <topic bytes><payload bytes>

FLUSH atomically (as far as a regular file is concerned) replaces the log
with ``FLUSH <next-sequence>\\n``.  Records use length prefixes, so arbitrary
payloads including NUL and newline bytes are safe.
"""

from __future__ import annotations

import os
from typing import BinaryIO, List, Optional, Tuple

from .storage import Event


class AOFError(Exception):
    """Base AOF failure."""


class AOFTruncated(AOFError):
    """A complete header exists but its payload bytes are missing."""


class AOFCorrupt(AOFError):
    """The AOF contains invalid data that cannot be safely replayed."""


def _read_exact(stream: BinaryIO, size: int) -> bytes:
    chunks: List[bytes] = []
    remaining = size
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


class AOFWriter:
    def __init__(self, path: str = ".linebus.aof", *, fsync: bool = False) -> None:
        self.path = path
        self.fsync = fsync
        self._file: Optional[BinaryIO] = None

    def open_for_append(self) -> None:
        if self._file is None:
            self._file = open(self.path, "ab+")

    def close(self) -> None:
        if self._file is not None:
            try:
                self._file.flush()
                if self.fsync:
                    os.fsync(self._file.fileno())
            finally:
                self._file.close()
                self._file = None

    def __enter__(self) -> "AOFWriter":
        self.open_for_append()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def append_event(self, event: Event) -> None:
        if self._file is None:
            raise AOFError("AOF file is not open")
        topic_bytes = event.topic.encode("utf-8")
        line = f"P {event.sequence} {len(topic_bytes)} {len(event.payload)}\n".encode("ascii")
        # One write call gives ordinary local file append semantics; broker
        # locking additionally guarantees call order equals execution order.
        self._file.write(line + topic_bytes + event.payload)
        self._file.flush()
        if self.fsync:
            os.fsync(self._file.fileno())

    def reset(self, next_sequence: int = 1) -> None:
        if self._file is None:
            raise AOFError("AOF file is not open")
        self._file.seek(0)
        self._file.truncate()
        self._file.write(f"FLUSH {next_sequence}\n".encode("ascii"))
        self._file.flush()
        if self.fsync:
            os.fsync(self._file.fileno())


def read_aof(path: str) -> Tuple[List[Event], int]:
    """Read and validate an AOF.

    Returns ``(events, next_sequence)``. A missing file yields an empty log and
    sequence 1. A partially written final record raises :class:`AOFTruncated`
    rather than silently deleting data.
    """
    if not os.path.exists(path):
        return [], 1
    events: List[Event] = []
    next_sequence = 1
    with open(path, "rb") as stream:
        while True:
            header = stream.readline()
            if not header:
                break
            if not header.endswith(b"\n"):
                raise AOFTruncated("AOF ends in the middle of a header")
            header_text = header[:-1].decode("ascii", errors="replace")
            parts = header_text.split(" ")
            try:
                if parts[0] == "P" and len(parts) == 4:
                    sequence = int(parts[1], 10)
                    topic_len = int(parts[2], 10)
                    payload_len = int(parts[3], 10)
                    if sequence < 1 or topic_len <= 0 or payload_len < 0:
                        raise ValueError
                    blob = _read_exact(stream, topic_len + payload_len)
                    if len(blob) != topic_len + payload_len:
                        raise AOFTruncated("AOF ends in the middle of a record")
                    topic_bytes, payload = blob[:topic_len], blob[topic_len:]
                    topic = topic_bytes.decode("utf-8")
                    expected = events[-1].sequence + 1 if events else 1
                    if sequence != expected:
                        raise AOFCorrupt(f"expected sequence {expected}, got {sequence}")
                    if (
                        not topic
                        or any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in topic)
                        or ("*" in topic)
                    ):
                        raise AOFCorrupt("invalid topic in AOF")
                    events.append(Event(sequence, topic, payload))
                elif parts[0] == "FLUSH" and len(parts) == 2:
                    next_sequence = int(parts[1], 10)
                    if next_sequence < 1:
                        raise ValueError
                    events = []
                else:
                    raise ValueError
            except (UnicodeDecodeError, ValueError) as exc:
                if isinstance(exc, AOFError):
                    raise
                raise AOFCorrupt(f"invalid AOF header: {header_text!r}") from exc
    if events:
        next_sequence = events[-1].sequence + 1
    return events, next_sequence
