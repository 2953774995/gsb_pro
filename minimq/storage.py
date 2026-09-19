"""Append-only on-disk log storage with a self-describing record format.

Record layout (all integers big-endian / network order)::

    +---------------+-------------------+----------------+----------+
    | magic (1 byte)| length (4 bytes)  | offset (8 byte)| payload  |
    +---------------+-------------------+----------------+----------+
    |  payload  | crc32 (4 bytes) |
    +----------+-----------------+

* ``magic``  : always ``0x4D`` ("M") - lets a reader detect / skip
  unknown framing.
* ``length`` : number of bytes in ``payload`` (uint32).
* ``offset`` : the monotonically increasing message offset (uint64).
* ``payload``: raw message bytes.
* ``crc32``  : CRC-32 (``zlib.crc32``) of *everything before the checksum*,
  i.e. magic + length + offset + payload.

The log is append-only. On recovery every complete record is validated;
a torn / corrupt tail record (short write, bad checksum, truncated length
prefix, ...) is truncated away safely so a crashed process never prevents
the broker from starting.
"""

import os
import struct
import zlib

MAGIC = 0x4D
_HEADER = struct.Struct(">BIQ")  # magic, length, offset
_CRC = struct.Struct(">I")

# Header: magic(1) + length(4) + offset(8) = 13 bytes; footer crc = 4 bytes.
FIXED_OVERHEAD = _HEADER.size + _CRC.size
MAX_PAYLOAD = 0xFFFFFFFF  # uint32 length prefix limit


class LogStorage:
    """An append-only log file for one topic.

    The file is kept open in ``ab+`` mode. Reads are performed by seeking
    from the beginning (only needed during recovery / rewrite), writes are
    simple appends.
    """

    def __init__(self, path, fsync=True):
        self.path = path
        self.fsync = fsync
        self._fh = open(self.path, "ab+")

    # ------------------------------------------------------------------
    # writing
    # ------------------------------------------------------------------
    def append(self, offset, payload):
        """Append one record; returns the number of bytes written."""
        if not isinstance(payload, (bytes, bytearray)):
            raise TypeError("payload must be bytes")
        if len(payload) > MAX_PAYLOAD:
            raise ValueError("payload too large for length prefix")
        body = _HEADER.pack(MAGIC, len(payload), offset) + bytes(payload)
        record = body + _CRC.pack(zlib.crc32(body) & 0xFFFFFFFF)
        self._fh.write(record)
        self._fh.flush()
        if self.fsync:
            os.fsync(self._fh.fileno())
        return len(record)

    # ------------------------------------------------------------------
    # reading / recovery
    # ------------------------------------------------------------------
    def recover(self):
        """Read all valid records from disk.

        Returns ``(records, valid_bytes)`` where ``records`` is a list of
        ``(offset, payload)`` tuples and ``valid_bytes`` is the length of
        the uncorrupted prefix of the file. If the file contains a torn
        tail it is truncated to ``valid_bytes``.
        """
        self._fh.flush()
        records = []
        pos = 0
        filesize = os.path.getsize(self.path)
        with open(self.path, "rb") as f:
            while True:
                f.seek(pos)
                header = f.read(_HEADER.size)
                if len(header) == 0:
                    break  # clean EOF
                if len(header) < _HEADER.size:
                    break  # torn header
                magic, length, offset = _HEADER.unpack(header)
                if magic != MAGIC:
                    break  # corrupt / unknown framing
                payload = f.read(length)
                crc_bytes = f.read(_CRC.size)
                if len(payload) < length or len(crc_bytes) < _CRC.size:
                    break  # torn body / checksum
                (stored_crc,) = _CRC.unpack(crc_bytes)
                body = header + payload
                if zlib.crc32(body) & 0xFFFFFFFF != stored_crc:
                    break  # corrupt record
                records.append((offset, bytes(payload)))
                pos += _HEADER.size + length + _CRC.size
        if pos != filesize:
            # Drop the torn tail so later appends stay frame-aligned.
            self.truncate(pos)
        return records, pos

    def truncate(self, size):
        """Truncate the log file to exactly ``size`` bytes."""
        self._fh.close()
        with open(self.path, "r+b") as f:
            f.truncate(size)
            f.flush()
            os.fsync(f.fileno())
        self._fh = open(self.path, "ab+")

    def rewrite(self, records):
        """Atomically replace the whole log with ``records``.

        ``records`` is an iterable of ``(offset, payload)`` tuples. Used by
        retention compaction. A temp file in the same directory is fsynced
        and then ``os.replace``-d into place (atomic on POSIX/Windows).
        """
        directory = os.path.dirname(self.path) or "."
        tmp_path = "{}.rewrite.{}.tmp".format(self.path, os.getpid())
        try:
            with open(tmp_path, "wb") as f:
                for offset, payload in records:
                    body = _HEADER.pack(MAGIC, len(payload), offset) + bytes(payload)
                    f.write(body + _CRC.pack(zlib.crc32(body) & 0xFFFFFFFF))
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.path)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
        self._fh.close()
        self._fh = open(self.path, "ab+")

    def close(self):
        try:
            self._fh.flush()
            if self.fsync:
                os.fsync(self._fh.fileno())
        finally:
            self._fh.close()
