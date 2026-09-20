"""SHA-1 content-addressed, zlib-compressed object storage.

Loose objects live at ``.cfgvault/objects/xx/<remaining 38 hex chars>``.  The
hash covers a small type/length header followed by raw payload, similar to Git:

    b"<type> <payload length>\\n" + payload

Object files are zlib-compressed serialisations of that same byte sequence.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
import tempfile
import zlib
from pathlib import Path

from .errors import CfgvaultError

BLOB = "blob"
TREE = "tree"
SNAPSHOT = "snapshot"
OBJECT_TYPES = frozenset((BLOB, TREE, SNAPSHOT))

DIR_MODE = "40000"
DEFAULT_FILE_MODE = "100644"
EXEC_FILE_MODE = "100755"
_OID_RE = re.compile(r"^[0-9a-f]{40}$")


def objects_dir(root: Path) -> Path:
    return root / ".cfgvault" / "objects"


def object_path(root: Path, oid: str) -> Path:
    """Return the loose-object path for a complete 40-character SHA-1."""
    validate_oid(oid)
    return objects_dir(root) / oid[:2] / oid[2:]


def validate_oid(oid: str) -> None:
    if not isinstance(oid, str) or not _OID_RE.fullmatch(oid):
        raise CfgvaultError(
            f"invalid object hash {oid!r}: expected 40 lowercase hexadecimal characters"
        )


def object_id(object_type: str, payload: bytes) -> str:
    """Compute the content hash, including the object header."""
    if object_type not in OBJECT_TYPES:
        raise CfgvaultError(f"unknown object type {object_type!r}")
    hasher = hashlib.sha1()
    hasher.update(f"{object_type} {len(payload)}\n".encode("ascii"))
    hasher.update(payload)
    return hasher.hexdigest()


def hash_blob_bytes(data: bytes) -> str:
    """Hash raw blob content (without storing it)."""
    return object_id(BLOB, data)


def hash_blob_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Hash file content in one streaming pass, using its size for the header."""
    size = os.path.getsize(path)
    hasher = hashlib.sha1()
    hasher.update(f"{BLOB} {size}\n".encode("ascii"))
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def file_mode(path: Path) -> str:
    """Return the POSIX mode stored for a regular working-tree file."""
    mode = path.stat().st_mode
    if stat.S_ISREG(mode):
        return EXEC_FILE_MODE if mode & 0o111 else DEFAULT_FILE_MODE
    # cfgvault intentionally supports ordinary JSON/text configuration files.
    raise CfgvaultError(f"unsupported file type: {path}")


def _atomic_compressed_write(path: Path, record: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".tmp-", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            # A small level gives compression without making multi-MB files
            # noticeably slow on locked-down office machines.
            compressor = zlib.compressobj(level=6)
            handle.write(compressor.compress(record))
            handle.write(compressor.flush())
        os.replace(tmp_path, path)
    except BaseException:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise


def write_object(root: Path, object_type: str, payload: bytes) -> str:
    """Write an object unless an identical object already exists; return ID."""
    oid = object_id(object_type, payload)
    destination = object_path(root, oid)
    if destination.exists():
        return oid
    record = f"{object_type} {len(payload)}\n".encode("ascii") + payload
    _atomic_compressed_write(destination, record)
    return oid


def write_blob_bytes(root: Path, data: bytes) -> str:
    return write_object(root, BLOB, data)


def write_blob_file(root: Path, source: Path, chunk_size: int = 1024 * 1024) -> str:
    """Write a file blob in chunks and return its object ID.

    The expected hash is calculated up front so an interrupted large file does
    not leave an object under an unrelated name.
    """
    expected = hash_blob_file(source, chunk_size=chunk_size)
    destination = object_path(root, expected)
    if destination.exists():
        return expected

    destination.parent.mkdir(parents=True, exist_ok=True)
    size = os.path.getsize(source)
    fd, tmp_name = tempfile.mkstemp(prefix=".tmp-", dir=str(objects_dir(root)))
    tmp_path = Path(tmp_name)
    try:
        compressor = zlib.compressobj(level=6)
        with os.fdopen(fd, "wb") as out, source.open("rb") as inp:
            out.write(compressor.compress(f"{BLOB} {size}\n".encode("ascii")))
            while True:
                chunk = inp.read(chunk_size)
                if not chunk:
                    break
                out.write(compressor.compress(chunk))
            out.write(compressor.flush())
        os.replace(tmp_path, destination)
    except BaseException:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise
    return expected


def read_object(root: Path, oid: str) -> Tuple[str, bytes]:
    """Read and verify an object, returning ``(object_type, payload)``."""
    validate_oid(oid)
    path = object_path(root, oid)
    if not path.exists():
        raise CfgvaultError(f"object not found: {oid}")
    try:
        record = zlib.decompress(path.read_bytes())
    except zlib.error as exc:
        raise CfgvaultError(f"object {oid} is corrupted: invalid zlib data") from exc

    newline = record.find(b"\n")
    if newline < 0:
        raise CfgvaultError(f"object {oid} is corrupted: missing object header")
    try:
        header = record[:newline].decode("ascii")
        object_type, length_text = header.split(" ", 1)
        length = int(length_text)
    except (UnicodeDecodeError, ValueError) as exc:
        raise CfgvaultError(f"object {oid} is corrupted: invalid header") from exc
    if object_type not in OBJECT_TYPES:
        raise CfgvaultError(f"object {oid} has unsupported type {object_type!r}")
    payload = record[newline + 1 :]
    if len(payload) != length:
        raise CfgvaultError(
            f"object {oid} is corrupted: expected {length} payload bytes, got {len(payload)}"
        )
    if object_id(object_type, payload) != oid:
        raise CfgvaultError(f"object {oid} is corrupted: hash mismatch")
    return object_type, payload


def read_blob(root: Path, oid: str) -> bytes:
    object_type, payload = read_object(root, oid)
    if object_type != BLOB:
        raise CfgvaultError(f"object {oid} is {object_type}, expected blob")
    return payload


def iter_object_ids(root: Path) -> list[str]:
    """List all complete object IDs currently present in the loose store."""
    base = objects_dir(root)
    result: list[str] = []
    if not base.exists():
        return result
    for prefix_dir in sorted(base.iterdir()):
        if not (prefix_dir.is_dir() and re.fullmatch(r"[0-9a-f]{2}", prefix_dir.name)):
            continue
        for item in sorted(prefix_dir.iterdir()):
            oid = prefix_dir.name + item.name
            if item.is_file() and _OID_RE.fullmatch(oid):
                result.append(oid)
    return result
