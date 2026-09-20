"""ZIP container reading and writing (PKZIP APPNOTE layout), no compression libs."""

from __future__ import annotations

import os
import stat
import struct
import time
from binascii import crc32
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .deflate import deflate, inflate

LOCAL_HEADER_SIG = 0x04034B50
CENTRAL_HEADER_SIG = 0x02014B50
EOCD_SIG = 0x06054B50

METHOD_STORED = 0
METHOD_DEFLATE = 8

UTF8_FLAG = 0x800
VERSION_NEEDED = 20  # 2.0: deflate support

_EPOCH = (1980, 1, 1, 0, 0, 0)


class ZipError(Exception):
    """Raised for malformed archives or integrity check failures."""


def _dos_datetime(dt: Tuple[int, int, int, int, int, int]) -> Tuple[int, int]:
    """Pack a ``(year, month, day, hour, minute, second)`` tuple as DOS date/time."""
    year, month, day, hour, minute, second = dt
    year = max(1980, min(2107, year))
    dos_time = (hour << 11) | (minute << 5) | (second // 2)
    dos_date = ((year - 1980) << 9) | (month << 5) | day
    return dos_time, dos_date


def _from_dos_datetime(dos_time: int, dos_date: int) -> Tuple[int, int, int, int, int, int]:
    second = (dos_time & 0x1F) * 2
    minute = (dos_time >> 5) & 0x3F
    hour = (dos_time >> 11) & 0x1F
    day = dos_date & 0x1F
    month = (dos_date >> 5) & 0x0F
    year = ((dos_date >> 9) & 0x7F) + 1980
    return (year, month, day, hour, minute, second)


def _encode_name(name: str) -> Tuple[bytes, int]:
    """Encode an archive member name; returns ``(bytes, general_purpose_flags)``."""
    try:
        return name.encode("ascii"), 0
    except UnicodeEncodeError:
        return name.encode("utf-8"), UTF8_FLAG


@dataclass
class ZipMember:
    """Metadata for one archive member."""

    filename: str
    compress_type: int
    compressed_size: int
    uncompressed_size: int
    crc32: int
    date_time: Tuple[int, int, int, int, int, int] = _EPOCH
    external_attr: int = 0
    flags: int = 0
    local_header_offset: int = 0
    extra: bytes = b""
    comment: bytes = b""

    @property
    def is_dir(self) -> bool:
        return self.filename.endswith("/")

    @property
    def compress_ratio(self) -> float:
        if self.uncompressed_size == 0:
            return 0.0
        return 1.0 - self.compressed_size / self.uncompressed_size


class ZipWriter:
    """Write a .zip file from local headers, a central directory and an EOCD."""

    def __init__(self, target, compresslevel: int = 6):
        if isinstance(target, (str, os.PathLike)):
            self._fp = open(target, "wb")
            self._own = True
        else:
            self._fp = target
            self._own = False
        self.compresslevel = compresslevel
        self._members: List[Tuple[ZipMember, bytes]] = []
        self._closed = False

    # -- adding content ----------------------------------------------------

    def writestr(
        self,
        name: str,
        data: bytes,
        date_time: Optional[Tuple[int, int, int, int, int, int]] = None,
        is_dir: bool = False,
        external_attr: int = 0,
    ) -> ZipMember:
        if self._closed:
            raise ValueError("ZipWriter is closed")
        if isinstance(data, str):
            data = data.encode("utf-8")
        name = name.replace("\\", "/")
        if is_dir and not name.endswith("/"):
            name += "/"
        if date_time is None:
            date_time = time.localtime()[:6]

        if is_dir:
            method, payload = METHOD_STORED, b""
            external_attr = external_attr or (0o40775 << 16) | 0x10
        else:
            compressed = deflate(bytes(data), level=self.compresslevel)
            if len(compressed) < len(data):
                method, payload = METHOD_DEFLATE, compressed
            else:
                method, payload = METHOD_STORED, bytes(data)
            external_attr = external_attr or (0o100644 << 16)

        member = ZipMember(
            filename=name,
            compress_type=method,
            compressed_size=len(payload),
            uncompressed_size=0 if is_dir else len(data),
            crc32=0 if is_dir else crc32(data) & 0xFFFFFFFF,
            date_time=date_time,
            external_attr=external_attr,
        )
        self._members.append((member, payload))
        return member

    def write(self, path: str, arcname: Optional[str] = None) -> None:
        """Add a filesystem file or directory (recursively) to the archive."""
        path = os.fspath(path)
        if arcname is None:
            arcname = os.path.basename(path.rstrip("/"))
        st = os.stat(path)
        date_time = time.localtime(st.st_mtime)[:6]
        if os.path.isdir(path):
            self.writestr(
                arcname + "/",
                b"",
                date_time=date_time,
                is_dir=True,
                external_attr=(stat.S_IMODE(st.st_mode) << 16) | 0o40755 << 0 | 0x10,
            )
            for root, dirs, files in os.walk(path):
                dirs.sort()
                for filename in sorted(files):
                    full = os.path.join(root, filename)
                    rel = os.path.relpath(full, path)
                    self.write(full, os.path.join(arcname, rel))
        else:
            with open(path, "rb") as fh:
                data = fh.read()
            self.writestr(
                arcname,
                data,
                date_time=date_time,
                external_attr=(stat.S_IMODE(st.st_mode) << 16) | (0o100000 << 16),
            )

    # -- finishing ----------------------------------------------------------

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            for member, payload in self._members:
                member.local_header_offset = self._fp.tell()
                name_bytes, flags = _encode_name(member.filename)
                member.flags = flags
                dos_time, dos_date = _dos_datetime(member.date_time)
                self._fp.write(
                    struct.pack(
                        "<IHHHHHIIIHH",
                        LOCAL_HEADER_SIG,
                        VERSION_NEEDED,
                        flags,
                        member.compress_type,
                        dos_time,
                        dos_date,
                        member.crc32,
                        member.compressed_size,
                        member.uncompressed_size,
                        len(name_bytes),
                        len(member.extra),
                    )
                )
                self._fp.write(name_bytes)
                self._fp.write(member.extra)
                self._fp.write(payload)

            cd_offset = self._fp.tell()
            for member, _payload in self._members:
                name_bytes, _flags = _encode_name(member.filename)
                dos_time, dos_date = _dos_datetime(member.date_time)
                self._fp.write(
                    struct.pack(
                        "<IHHHHHHIIIHHHHHII",
                        CENTRAL_HEADER_SIG,
                        VERSION_NEEDED,  # version made by
                        VERSION_NEEDED,
                        member.flags,
                        member.compress_type,
                        dos_time,
                        dos_date,
                        member.crc32,
                        member.compressed_size,
                        member.uncompressed_size,
                        len(name_bytes),
                        len(member.extra),
                        len(member.comment),
                        0,  # disk number start
                        0,  # internal attributes
                        member.external_attr,
                        member.local_header_offset,
                    )
                )
                self._fp.write(name_bytes)
                self._fp.write(member.extra)
                self._fp.write(member.comment)
            cd_size = self._fp.tell() - cd_offset

            self._fp.write(
                struct.pack(
                    "<IHHHHIIH",
                    EOCD_SIG,
                    0,
                    0,
                    len(self._members),
                    len(self._members),
                    cd_size,
                    cd_offset,
                    0,
                )
            )
        finally:
            if self._own:
                self._fp.close()

    def __enter__(self) -> "ZipWriter":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


class ZipReader:
    """Parse a .zip file via its central directory and extract members."""

    def __init__(self, source):
        if isinstance(source, (str, os.PathLike)):
            with open(source, "rb") as fh:
                self._data = fh.read()
        elif isinstance(source, (bytes, bytearray)):
            self._data = bytes(source)
        else:
            self._data = source.read()
        self._members: List[ZipMember] = []
        self._by_name: Dict[str, ZipMember] = {}
        self._parse()

    def _parse(self) -> None:
        data = self._data
        # The EOCD record is 22 bytes plus up to 65535 bytes of comment.
        search_from = max(0, len(data) - (22 + 65535))
        eocd_at = data.rfind(struct.pack("<I", EOCD_SIG), search_from)
        if eocd_at < 0:
            raise ZipError("not a zip file: end of central directory not found")
        (
            _sig,
            _disk,
            _cd_disk,
            _count_disk,
            count,
            cd_size,
            cd_offset,
            comment_len,
        ) = struct.unpack_from("<IHHHHIIH", data, eocd_at)
        if eocd_at + 22 + comment_len > len(data):
            raise ZipError("truncated end of central directory")
        if cd_offset + cd_size > len(data):
            raise ZipError("central directory points outside the file")

        pos = cd_offset
        for _ in range(count):
            if pos + 46 > len(data) or struct.unpack_from("<I", data, pos)[0] != CENTRAL_HEADER_SIG:
                raise ZipError("bad central directory entry")
            (
                _sig,
                _made,
                _needed,
                flags,
                method,
                dos_time,
                dos_date,
                crc,
                comp_size,
                uncomp_size,
                name_len,
                extra_len,
                comment_len,
                _disk_start,
                _internal,
                external_attr,
                local_offset,
            ) = struct.unpack_from("<IHHHHHHIIIHHHHHII", data, pos)
            pos += 46
            name_raw = data[pos:pos + name_len]
            pos += name_len
            extra = data[pos:pos + extra_len]
            pos += extra_len
            comment = data[pos:pos + comment_len]
            pos += comment_len
            if len(name_raw) != name_len:
                raise ZipError("truncated central directory entry")
            codec = "utf-8" if flags & UTF8_FLAG else "cp437"
            name = name_raw.decode(codec, errors="replace")
            member = ZipMember(
                filename=name,
                compress_type=method,
                compressed_size=comp_size,
                uncompressed_size=uncomp_size,
                crc32=crc,
                date_time=_from_dos_datetime(dos_time, dos_date),
                external_attr=external_attr,
                flags=flags,
                local_header_offset=local_offset,
                extra=extra,
                comment=comment,
            )
            self._members.append(member)
            self._by_name.setdefault(name, member)

    # -- introspection -------------------------------------------------------

    def infolist(self) -> List[ZipMember]:
        return list(self._members)

    def namelist(self) -> List[str]:
        return [m.filename for m in self._members]

    def getmember(self, name: str) -> ZipMember:
        name = name.replace("\\", "/")
        if name in self._by_name:
            return self._by_name[name]
        raise KeyError(f"no member named {name!r}")

    # -- extraction ----------------------------------------------------------

    def _member_payload(self, member: ZipMember) -> bytes:
        data = self._data
        offset = member.local_header_offset
        if offset + 30 > len(data) or struct.unpack_from("<I", data, offset)[0] != LOCAL_HEADER_SIG:
            raise ZipError(f"bad local file header for {member.filename!r}")
        name_len, extra_len = struct.unpack_from("<HH", data, offset + 26)
        start = offset + 30 + name_len + extra_len
        end = start + member.compressed_size
        if end > len(data):
            raise ZipError(f"truncated data for {member.filename!r}")
        return data[start:end]

    def read(self, name: str) -> bytes:
        member = self.getmember(name)
        payload = self._member_payload(member)
        if member.compress_type == METHOD_STORED:
            result = payload
        elif member.compress_type == METHOD_DEFLATE:
            try:
                result = inflate(payload, expected_size=member.uncompressed_size)
            except (ValueError, EOFError) as exc:
                raise ZipError(f"cannot inflate {member.filename!r}: {exc}") from exc
        else:
            raise ZipError(
                f"unsupported compression method {member.compress_type} for {member.filename!r}"
            )
        if len(result) != member.uncompressed_size:
            raise ZipError(
                f"size mismatch for {member.filename!r}: "
                f"expected {member.uncompressed_size}, got {len(result)}"
            )
        if crc32(result) & 0xFFFFFFFF != member.crc32:
            raise ZipError(f"CRC32 mismatch for {member.filename!r}")
        return result

    def extractall(self, dest: str) -> List[str]:
        """Extract every member under ``dest``; returns created file paths."""
        written: List[str] = []
        for member in self._members:
            rel = member.filename
            # Guard against absolute paths and '..' traversal.
            parts = [p for p in rel.split("/") if p not in ("", ".", "..")]
            if not parts:
                continue
            target = os.path.join(dest, *parts)
            if member.is_dir:
                os.makedirs(target, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(target) or dest, exist_ok=True)
            content = self.read(member.filename)
            with open(target, "wb") as fh:
                fh.write(content)
            try:
                ts = time.mktime(member.date_time + (0, 0, -1))
                os.utime(target, (ts, ts))
            except (ValueError, OverflowError, OSError):
                pass
            written.append(target)
        return written


# -- convenience API ----------------------------------------------------------

def write_zip(path, items: Dict[str, bytes], compresslevel: int = 6) -> None:
    with ZipWriter(path, compresslevel=compresslevel) as zw:
        for name, data in items.items():
            zw.writestr(name, data)


def list_zip(path) -> List[ZipMember]:
    return ZipReader(path).infolist()


def extract_zip(path, dest: str) -> List[str]:
    return ZipReader(path).extractall(dest)
