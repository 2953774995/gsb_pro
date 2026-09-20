"""Append-only persistence for published events.

The AOF reuses the length-prefixed network event framing::

    LINEBUS-AOF/1
    EVENT <sequence> <topic> <payload-length>\n
    <payload>\n

Because payloads are length-prefixed, arbitrary bytes can be stored safely.
Every successful PUBLISH is flushed and fsynced before its response is returned.
"""

from __future__ import annotations

import os
from pathlib import Path

from .protocol import DEFAULT_MAX_COMMAND_SIZE, encode_event
from .storage import Event, validate_topic


MAGIC = b"LINEBUS-AOF/1\n"


class AOFError(Exception):
    """Raised when an AOF cannot be read or written."""


class AppendOnlyLog:
    def __init__(self, path: str | os.PathLike[str]):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(self.path, "ab+", buffering=0)

    def initialize(self) -> None:
        if self.path.stat().st_size == 0:
            self._write_all(MAGIC, sync=True)

    def append(self, event: Event) -> None:
        try:
            self._write_all(encode_event(event.sequence, event.topic, event.payload), sync=True)
        except OSError as exc:
            raise AOFError(f"failed to append event {event.sequence}: {exc}") from exc

    def _write_all(self, data: bytes, *, sync: bool) -> None:
        self._file.write(data)
        self._file.flush()
        if sync:
            os.fsync(self._file.fileno())

    def truncate(self) -> None:
        try:
            self._file.seek(0)
            self._file.truncate()
            self._file.write(MAGIC)
            self._file.flush()
            os.fsync(self._file.fileno())
        except OSError as exc:
            raise AOFError(f"failed to flush AOF: {exc}") from exc

    def close(self) -> None:
        try:
            self._file.flush()
        finally:
            self._file.close()

    @classmethod
    def load(cls, path: str | os.PathLike[str], max_command_size: int = DEFAULT_MAX_COMMAND_SIZE):
        path = Path(path)
        if not path.exists() or path.stat().st_size == 0:
            return [], 1
        with open(path, "rb") as fh:
            data = fh.read()
        if not data.startswith(MAGIC):
            raise AOFError("invalid AOF magic header")

        events: list[Event] = []
        offset = len(MAGIC)
        while offset < len(data):
            frame_start = offset
            line_end = data.find(b"\n", offset)
            if line_end < 0:
                cls._truncate_tail(path, frame_start, "partial AOF header")
                break
            header = data[offset:line_end]
            prefix = header.split(b" ", 2)
            if len(prefix) != 3 or prefix[0] != b"EVENT":
                raise AOFError(f"corrupt AOF record header at byte {offset}")
            rest = prefix[2]
            last_space = rest.rfind(b" ")
            if last_space < 0:
                raise AOFError(f"corrupt AOF record header at byte {offset}")
            try:
                sequence = int(prefix[1])
                payload_length = int(rest[last_space + 1 :])
            except ValueError as exc:
                raise AOFError(f"corrupt AOF record header at byte {offset}") from exc
            topic = rest[:last_space].decode("utf-8", errors="strict")
            try:
                validate_topic(topic)
            except (UnicodeError, ValueError) as exc:
                raise AOFError(f"corrupt AOF topic at byte {offset}") from exc
            if sequence < 1 or payload_length < 0 or payload_length > max_command_size:
                raise AOFError(f"invalid AOF record bounds at byte {offset}")
            if events and sequence != events[-1].sequence + 1:
                raise AOFError(f"non-contiguous AOF sequence at byte {offset}")
            payload_end = line_end + 1 + payload_length
            if payload_end >= len(data):
                # The final record can be torn by an OS process crash/power loss.
                cls._truncate_tail(path, frame_start, "partial AOF payload")
                break
            if data[payload_end] != 0x0A:
                raise AOFError(f"missing AOF payload terminator at byte {payload_end}")
            payload = data[line_end + 1 : payload_end]
            events.append(Event(sequence, topic, bytes(payload)))
            offset = payload_end + 1
        next_sequence = events[-1].sequence + 1 if events else 1
        return events, next_sequence

    @staticmethod
    def _truncate_tail(path: Path, valid_end_relative_to_body: int, reason: str) -> None:
        # valid_end is relative to the first byte after MAGIC.
        valid_end = len(MAGIC) + valid_end_relative_to_body
        with open(path, "r+b") as fh:
            fh.seek(valid_end)
            fh.truncate()
            fh.flush()
            os.fsync(fh.fileno())
