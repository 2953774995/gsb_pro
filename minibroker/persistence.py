"""Append-only-file persistence.

Each AOF record is one length-prefixed array frame::

    ["MSG", decimal-sequence, topic, payload]

Using the network wire format for disk records means topics and payloads can
contain arbitrary bytes and no separate escaping layer is necessary.  A
best-effort ``fsync`` follows each append, so an acknowledged PUBLISH survives
ordinary process termination.
"""

from __future__ import annotations

import fcntl
import os
from dataclasses import dataclass
from typing import BinaryIO, List, Optional

from . import protocol
from .protocol import ProtocolError
from .exceptions import PersistenceError
from .messages import StoredMessage


@dataclass(frozen=True)
class ReplayResult:
    messages: List[StoredMessage]
    next_sequence: int


class AppendOnlyLog:
    def __init__(self, path: str, *, enabled: bool = True):
        self.path = path
        self.enabled = enabled
        self._file: Optional[BinaryIO] = None
        self._lock_fd: Optional[int] = None
        self._closed = False

        if enabled:
            directory = os.path.dirname(os.path.abspath(path))
            os.makedirs(directory, exist_ok=True)
            # Acquire an advisory lock for the lifetime of this broker.  This
            # gives a clear failure if two servers try to share one AOF.
            self._lock_fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
            try:
                fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                os.close(self._lock_fd)
                self._lock_fd = None
                raise PersistenceError(f"AOF {path!r} is already in use") from exc
            self._file = open(path, "r+b", buffering=0)

    @classmethod
    def null(cls) -> "AppendOnlyLog":
        log = cls.__new__(cls)
        log.path = ""
        log.enabled = False
        log._file = None
        log._lock_fd = None
        log._closed = False
        return log

    def replay(self) -> ReplayResult:
        if not self.enabled:
            return ReplayResult([], 1)

        assert self._file is not None
        self._file.seek(0)
        messages: List[StoredMessage] = []
        good_end = 0

        try:
            while True:
                first = self._file.read(1)
                if not first:
                    break
                self._file.seek(-1, os.SEEK_CUR)
                record_start = self._file.tell()
                try:
                    frame = protocol.read_frame(self._file, max_size=None)
                except EOFError:
                    # Truncated trailing write: keep all complete records.
                    self._file.truncate(record_start)
                    break
                except (ProtocolError, ValueError, TypeError):
                    raise PersistenceError(
                        f"corrupt AOF record at byte {record_start}"
                    )

                if (
                    len(frame) != 4
                    or frame[0] != b"MSG"
                ):
                    raise PersistenceError(
                        f"unsupported AOF record at byte {record_start}"
                    )
                try:
                    sequence = int(frame[1])
                except ValueError as exc:
                    raise PersistenceError("AOF record has non-integer sequence") from exc
                if sequence < 1:
                    raise PersistenceError("AOF record has invalid sequence")
                if messages and sequence != messages[-1].sequence + 1:
                    raise PersistenceError("AOF sequence numbers are not contiguous")
                messages.append(StoredMessage(sequence, frame[2], frame[3]))
                good_end = self._file.tell()
        except PersistenceError:
            self._file.truncate(good_end)
            raise

        next_sequence = messages[-1].sequence + 1 if messages else 1
        self._file.seek(0, os.SEEK_END)
        return ReplayResult(messages, next_sequence)

    def append(self, message: StoredMessage) -> None:
        if not self.enabled:
            return
        if self._closed or self._file is None:
            raise PersistenceError("AOF is closed")

        frame = protocol.encode_frame(
            [b"MSG", str(message.sequence).encode("ascii"), message.topic, message.payload]
        )
        try:
            self._file.write(frame)
            self._file.flush()
            os.fsync(self._file.fileno())
        except OSError as exc:
            raise PersistenceError("failed to append to AOF") from exc

    def flush(self) -> None:
        if not self.enabled:
            return
        if self._closed or self._file is None:
            raise PersistenceError("AOF is closed")
        try:
            self._file.seek(0)
            self._file.truncate()
            self._file.flush()
            os.fsync(self._file.fileno())
        except OSError as exc:
            raise PersistenceError("failed to flush AOF") from exc

    def close(self) -> None:
        if not self.enabled or self._closed:
            return
        self._closed = True
        try:
            if self._file is not None:
                self._file.close()
            if self._lock_fd is not None:
                fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
                os.close(self._lock_fd)
        finally:
            self._file = None
            self._lock_fd = None

    def __enter__(self) -> "AppendOnlyLog":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
