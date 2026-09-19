"""Append-only file persistence.

Each PUBLISH is appended as one self-delimiting frame::

    P <seq> <topic-byte-length> <payload-length>\n
    <topic bytes><payload bytes>

Topic is length-prefixed as well so it can theoretically carry any byte; the
protocol currently restricts topics to printable ASCII/UTF-8. The AOF records
the sequence number, so recovery restores both the messages and the global
sequence counter. A truncated trailing record (process killed mid-write) is
ignored rather than fatal.
"""

from __future__ import annotations

import os
import tempfile
from typing import List, Optional, Tuple

from .storage import Message

AOF_MAGIC = b"# minibroker AOF v1\n"


class AppendOnlyLog:
    def __init__(self, path: str, fsync: bool = False) -> None:
        self.path = path
        self.fsync = fsync
        self._file = None

    def open_for_append(self) -> None:
        new_file = not os.path.exists(self.path) or os.path.getsize(self.path) == 0
        # line buffered binary isn't supported; flush explicitly after writes
        self._file = open(self.path, "ab")
        if new_file:
            self._file.write(AOF_MAGIC)
            self._file.flush()

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None

    def append_message(self, message: Message) -> None:
        if self._file is None:
            raise RuntimeError("AOF is not open")
        topic_b = message.topic.encode("utf-8")
        header = b"P %d %d %d\n" % (
            message.seq,
            len(topic_b),
            len(message.payload),
        )
        self._file.write(header + topic_b + bytes(message.payload))
        # Order with execution order: flush before the publish is acknowledged.
        self._file.flush()
        if self.fsync:
            os.fsync(self._file.fileno())

    def truncate(self) -> None:
        """Forget all history (FLUSH): reset the file to the magic header."""
        if self._file is not None:
            self._file.close()
            self._file = None
        with open(self.path, "wb") as handle:
            handle.write(AOF_MAGIC)
            handle.flush()
        self._file = open(self.path, "ab")

    @staticmethod
    def recover(path: str) -> Tuple[List[Message], int]:
        """Read all frames back; return (messages, highest sequence)."""
        messages: List[Message] = []
        max_seq = 0
        if not os.path.exists(path):
            return messages, max_seq
        with open(path, "rb") as handle:
            data = handle.read()
        pos = 0
        if data.startswith(AOF_MAGIC):
            pos = len(AOF_MAGIC)
        total = len(data)
        while pos < total:
            line_end = data.find(b"\n", pos)
            if line_end == -1:
                break  # truncated trailing header
            header = data[pos:line_end]
            pos = line_end + 1
            parts = header.split(b" ")
            if len(parts) != 4 or parts[0] != b"P":
                # Unknown/garbage record: stop recovery rather than guess.
                break
            try:
                seq = int(parts[1])
                topic_len = int(parts[2])
                payload_len = int(parts[3])
            except ValueError:
                break
            frame_end = pos + topic_len + payload_len
            if frame_end > total:
                break  # truncated trailing frame
            topic_b = data[pos : pos + topic_len]
            payload = data[pos + topic_len : frame_end]
            pos = frame_end
            try:
                topic = topic_b.decode("utf-8")
            except UnicodeDecodeError:
                break
            messages.append(Message(seq=seq, topic=topic, payload=payload))
            max_seq = max(max_seq, seq)
        return messages, max_seq
