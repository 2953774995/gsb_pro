"""Append-only record log with length prefix + CRC32 checksum.

On-disk record format (all integers big-endian, unsigned)::

    +-------------------+-------------------+===================+
    | length (4 bytes)  | crc32 (4 bytes)   | payload (length)  |
    +-------------------+-------------------+===================+

The payload is a UTF-8 encoded JSON object: ``{"offset": int, "body": str}``.
The CRC32 is computed over the payload bytes only.

Recovery: the log is read sequentially. The first record that is
incomplete (torn header/payload) or fails its CRC check marks the end of
the valid log; the file is truncated at that point so a crashed write
(half a message) never breaks the broker.
"""

import json
import os
import struct
import zlib

_HEADER = struct.Struct(">II")  # (payload_length, crc32)


class RecordLog(object):
    """A single append-only log file storing (offset, body) records."""

    def __init__(self, path):
        self.path = path
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        # Touch the file so appends never fail on a missing file.
        if not os.path.exists(path):
            open(path, "ab").close()
        self._file = open(path, "ab")

    @staticmethod
    def _encode(offset, body):
        payload = json.dumps({"offset": offset, "body": body}).encode("utf-8")
        crc = zlib.crc32(payload) & 0xFFFFFFFF
        return _HEADER.pack(len(payload), crc) + payload

    def load(self):
        """Read all valid records, truncating a corrupt/torn tail.

        Returns a list of ``(offset, body)`` tuples.
        """
        records = []
        good_length = 0
        with open(self.path, "rb") as f:
            while True:
                header = f.read(_HEADER.size)
                if not header:
                    break  # clean EOF
                if len(header) < _HEADER.size:
                    break  # torn header
                length, crc = _HEADER.unpack(header)
                payload = f.read(length)
                if len(payload) < length:
                    break  # torn payload (half-written message)
                if (zlib.crc32(payload) & 0xFFFFFFFF) != crc:
                    break  # corrupted payload
                try:
                    record = json.loads(payload.decode("utf-8"))
                    records.append((int(record["offset"]), record["body"]))
                except (ValueError, KeyError, TypeError):
                    break  # undecodable record: treat as corruption
                good_length += _HEADER.size + length
        actual_size = os.path.getsize(self.path)
        if actual_size != good_length:
            # Safely truncate the corrupt tail; never raise.
            with open(self.path, "r+b") as f:
                f.truncate(good_length)
        return records

    def append(self, offset, body, fsync=True):
        data = self._encode(offset, body)
        self._file.write(data)
        self._file.flush()
        if fsync:
            os.fsync(self._file.fileno())

    def rewrite(self, records, fsync=True):
        """Atomically replace the whole log with ``records`` (compaction)."""
        tmp_path = self.path + ".tmp"
        with open(tmp_path, "wb") as f:
            for offset, body in records:
                f.write(self._encode(offset, body))
            f.flush()
            if fsync:
                os.fsync(f.fileno())
        os.replace(tmp_path, self.path)
        self._file.close()
        self._file = open(self.path, "ab")

    def close(self):
        if not self._file.closed:
            self._file.flush()
            self._file.close()
