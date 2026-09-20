"""PKZIP (.zip) container reading and writing.

Layout of a zip file (all integers little-endian)::

    [local file header 1][file data 1]
    [local file header 2][file data 2]
    ...
    [central directory entry 1]
    [central directory entry 2]
    ...
    [end of central directory record]

Local file header:      PK\\x03\\x04 ...
Central directory entry: PK\\x01\\x02 ...
End of central dir:     PK\\x05\\x06 ...

Sizes and CRCs are known before writing (we compress in memory first),
so no data descriptors are needed.
"""

import os
import struct
import time
from binascii import crc32

from . import deflate

METHOD_STORED = 0
METHOD_DEFLATE = 8

LOCAL_SIG = 0x04034B50
CENTRAL_SIG = 0x02014B50
EOCD_SIG = 0x06054B50

FLAG_UTF8 = 0x0800

_LOCAL_STRUCT = struct.Struct("<IHHHHHIIIHH")
_CENTRAL_STRUCT = struct.Struct("<IHHHHHHIIIHHHHHII")
_EOCD_STRUCT = struct.Struct("<IHHHHIIH")


class ZipError(Exception):
    """Malformed or unsupported zip archive."""


class CRCError(ZipError):
    """Extracted data does not match the stored CRC-32."""


def dos_datetime(ts):
    """Convert a POSIX timestamp to (dos_time, dos_date)."""
    t = time.localtime(ts)
    year = min(max(t.tm_year, 1980), 2107)
    dos_time = (t.tm_hour << 11) | (t.tm_min << 5) | (t.tm_sec // 2)
    dos_date = ((year - 1980) << 9) | (t.tm_mon << 5) | t.tm_mday
    return dos_time, dos_date


def from_dos_datetime(dos_time, dos_date):
    """Convert DOS date/time fields back to a POSIX timestamp."""
    year = ((dos_date >> 9) & 0x7F) + 1980
    month = (dos_date >> 5) & 0x0F
    day = dos_date & 0x1F
    hour = (dos_time >> 11) & 0x1F
    minute = (dos_time >> 5) & 0x3F
    second = (dos_time & 0x1F) * 2
    try:
        return time.mktime((year, month, day, hour, minute, second,
                            0, 0, -1))
    except (OverflowError, ValueError):
        return 0


class ZipInfo(object):
    __slots__ = ("name", "method", "file_size", "compress_size", "crc",
                 "header_offset", "dos_time", "dos_date", "is_dir")

    @property
    def mtime(self):
        return from_dos_datetime(self.dos_time, self.dos_date)

    def __repr__(self):
        return "ZipInfo(%r, size=%d)" % (self.name, self.file_size)


def write_zip(path, items):
    """Write a zip archive to ``path``.

    ``items`` is an iterable of ``(arcname, data, mtime)`` tuples.
    Names use '/' as separator; a name ending in '/' is a directory
    entry (its data is ignored).
    """
    central = []
    with open(path, "wb") as f:
        for name, data, mtime in items:
            name_b = name.encode("utf-8")
            is_dir = name.endswith("/")
            dos_time, dos_date = dos_datetime(mtime)
            if is_dir:
                comp = b""
                method = METHOD_STORED
                crc = 0
            else:
                comp = deflate.compress(data)
                method = METHOD_DEFLATE
                crc = crc32(data) & 0xFFFFFFFF
            offset = f.tell()
            f.write(_LOCAL_STRUCT.pack(
                LOCAL_SIG, 20, FLAG_UTF8, method, dos_time, dos_date,
                crc, len(comp), len(data), len(name_b), 0))
            f.write(name_b)
            f.write(comp)
            central.append((name_b, dos_time, dos_date, crc, len(comp),
                            len(data), offset, method, is_dir))
        cd_start = f.tell()
        for (name_b, dos_time, dos_date, crc, csize, usize, offset,
             method, is_dir) in central:
            ext_attr = (0o40755 if is_dir else 0o100644) << 16
            f.write(_CENTRAL_STRUCT.pack(
                CENTRAL_SIG, (3 << 8) | 20, 20, FLAG_UTF8, method,
                dos_time, dos_date, crc, csize, usize,
                len(name_b), 0, 0, 0, 0, ext_attr, offset))
            f.write(name_b)
        cd_size = f.tell() - cd_start
        f.write(_EOCD_STRUCT.pack(
            EOCD_SIG, 0, 0, len(central), len(central),
            cd_size, cd_start, 0))


def read_zip_directory(path):
    """Parse the central directory and return a list of ZipInfo."""
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        tail = min(size, 65557)     # EOCD (22) + max comment (65535)
        f.seek(size - tail)
        blob = f.read(tail)
        idx = blob.rfind(b"PK\x05\x06")
        if idx < 0:
            raise ZipError("not a zip file: end of central directory "
                           "record not found")
        (_sig, _disk, _cd_disk, _n_disk, n_total, cd_size,
         cd_offset, _clen) = _EOCD_STRUCT.unpack_from(blob, idx)
        f.seek(cd_offset)
        cd = f.read(cd_size)

    entries = []
    pos = 0
    for _ in range(n_total):
        if pos + _CENTRAL_STRUCT.size > len(cd):
            raise ZipError("truncated central directory")
        fields = _CENTRAL_STRUCT.unpack_from(cd, pos)
        if fields[0] != CENTRAL_SIG:
            raise ZipError("bad central directory signature")
        (_sig, _vmade, _vneed, _flags, method, dos_time, dos_date, crc,
         csize, usize, nlen, elen, clen, _disk, _iattr, _xattr,
         offset) = fields
        pos += _CENTRAL_STRUCT.size
        name = cd[pos:pos + nlen].decode("utf-8", "replace")
        pos += nlen + elen + clen
        info = ZipInfo()
        info.name = name
        info.method = method
        info.file_size = usize
        info.compress_size = csize
        info.crc = crc
        info.header_offset = offset
        info.dos_time = dos_time
        info.dos_date = dos_date
        info.is_dir = name.endswith("/")
        entries.append(info)
    return entries


def read_file(path, info):
    """Extract one member, verifying its CRC-32.  Returns bytes."""
    with open(path, "rb") as f:
        f.seek(info.header_offset)
        header = f.read(_LOCAL_STRUCT.size)
        if len(header) < _LOCAL_STRUCT.size:
            raise ZipError("truncated local file header")
        fields = _LOCAL_STRUCT.unpack(header)
        if fields[0] != LOCAL_SIG:
            raise ZipError("bad local file header signature")
        nlen, elen = fields[9], fields[10]
        f.seek(info.header_offset + _LOCAL_STRUCT.size + nlen + elen)
        comp = f.read(info.compress_size)
        if len(comp) < info.compress_size:
            raise ZipError("truncated file data")

    if info.method == METHOD_DEFLATE:
        data = deflate.decompress(comp, max_length=info.file_size)
    elif info.method == METHOD_STORED:
        data = comp
    else:
        raise ZipError("unsupported compression method %d" % info.method)
    if len(data) != info.file_size:
        raise ZipError("size mismatch for %r" % info.name)
    if (crc32(data) & 0xFFFFFFFF) != info.crc:
        raise CRCError("CRC-32 mismatch for %r" % info.name)
    return data
