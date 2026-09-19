"""Append-only file persistence.

Every published message is appended to the AOF *before* it is applied to
the in-memory state, and all appends happen under the broker lock, so the
file order always matches the execution order.

Record layout (binary safe)::

    AOF1 <seq> <topic_len> <payload_len>\n<topic bytes><payload bytes>

Additionally a checkpoint line may appear (written by FLUSH)::

    #SEQ <seq>\n

It records the last issued sequence number so that a restart after FLUSH
keeps the global sequence monotonically increasing.

Replay is tolerant of a torn write at the tail of the file: parsing stops
at the first incomplete/corrupt record.
"""

from __future__ import annotations

import os

from .protocol import read_line, read_exact, MAX_TOPIC_LEN

MAGIC = b"AOF1"
SEQ_PREFIX = b"#SEQ "
# Upper sanity bounds while replaying (corrupt length fields must not make
# us try to allocate/read absurd amounts).
_MAX_REPLAY_TOPIC = 64 * 1024
_MAX_REPLAY_PAYLOAD = 256 * 1024 * 1024


class AofWriter:
    """Appends publish records to the AOF.  Not thread-safe by itself; the
    broker serialises calls under its lock."""

    def __init__(self, path: str, fsync: bool = False):
        self._path = path
        self._fsync = fsync
        self._file = open(path, "ab")

    @property
    def path(self) -> str:
        return self._path

    def append(self, seq: int, topic: str, payload: bytes) -> None:
        topic_b = topic.encode("utf-8")
        header = (
            MAGIC + b" " + str(seq).encode("ascii") + b" "
            + str(len(topic_b)).encode("ascii") + b" "
            + str(len(payload)).encode("ascii") + b"\n"
        )
        self._file.write(header + topic_b + payload)
        self._file.flush()
        if self._fsync:
            os.fsync(self._file.fileno())

    def reset(self, last_seq: int) -> None:
        """Truncate the file, keeping only a sequence checkpoint."""
        self._file.close()
        self._file = open(self._path, "wb")
        self._file.write(SEQ_PREFIX + str(last_seq).encode("ascii") + b"\n")
        self._file.flush()
        if self._fsync:
            os.fsync(self._file.fileno())

    def close(self) -> None:
        try:
            self._file.close()
        except Exception:
            pass


def replay_aof(path: str):
    """Replay an AOF file.

    Returns ``(records, floor_seq)`` where *records* is a list of
    ``(seq, topic, payload)`` and *floor_seq* is the sequence checkpoint
    written by FLUSH (0 when absent).
    """
    records = []
    floor_seq = 0
    if not os.path.exists(path):
        return records, floor_seq
    with open(path, "rb") as f:
        while True:
            try:
                line = read_line(f, 4096)
            except (EOFError, StopIteration):
                break
            except Exception:
                break
            if line.startswith(SEQ_PREFIX):
                try:
                    floor_seq = int(line[len(SEQ_PREFIX):])
                except ValueError:
                    pass
                continue
            parts = line.split(b" ")
            if len(parts) != 4 or parts[0] != MAGIC:
                break  # corrupt record: stop replay
            try:
                seq = int(parts[1])
                tlen = int(parts[2])
                plen = int(parts[3])
            except ValueError:
                break
            if not (0 <= tlen <= _MAX_REPLAY_TOPIC) or not (0 <= plen <= _MAX_REPLAY_PAYLOAD):
                break
            try:
                topic_b = read_exact(f, tlen)
                payload = read_exact(f, plen)
            except EOFError:
                break  # torn write at tail
            records.append((seq, topic_b.decode("utf-8", "replace"), payload))
    return records, floor_seq
