"""SHA-1 content-addressed, zlib-compressed object storage."""

from __future__ import annotations

import hashlib
import os
import tempfile
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Mapping, Optional, Tuple

OBJECT_BLOB = b"blob"
OBJECT_TREE = b"tree"
OBJECT_COMMIT = b"commit"

FILE_MODE = "100644"
EXECUTABLE_MODE = "100755"
TREE_MODE = "40000"


class ObjectError(ValueError):
    pass


@dataclass(frozen=True)
class TreeEntry:
    mode: str
    name: str
    hash: str


def object_path(objects_dir: os.PathLike[str] | str, sha: str) -> Path:
    if len(sha) != 40 or any(c not in "0123456789abcdef" for c in sha.lower()):
        raise ObjectError(f"invalid object id: {sha!r}")
    return Path(objects_dir) / sha[:2] / sha[2:]


def exists(objects_dir: os.PathLike[str] | str, sha: str) -> bool:
    try:
        return object_path(objects_dir, sha).is_file()
    except ObjectError:
        return False


def _write_compressed(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        compressor = zlib.compressobj()
        with open(temporary, "wb") as handle:
            handle.write(compressor.compress(payload))
            handle.write(compressor.flush())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def write_object(objects_dir: os.PathLike[str] | str, object_type: bytes, data: bytes) -> str:
    """Store an in-memory object and return its SHA-1 hex ID."""
    if object_type not in (OBJECT_BLOB, OBJECT_TREE, OBJECT_COMMIT):
        raise ObjectError(f"unsupported object type: {object_type!r}")
    content = object_type + b" " + str(len(data)).encode("ascii") + b"\0" + data
    sha = hashlib.sha1(content).hexdigest()
    path = object_path(objects_dir, sha)
    if not path.exists():
        _write_compressed(path, content)
    return sha


def write_blob_from_path(objects_dir: os.PathLike[str] | str, file_path: os.PathLike[str] | str) -> Tuple[str, int]:
    """Stream a working-tree file into a blob without loading the entire file."""
    file_path = Path(file_path)
    size = file_path.stat().st_size
    header = OBJECT_BLOB + b" " + str(size).encode("ascii") + b"\0"
    digest = hashlib.sha1()
    digest.update(header)

    target_dir = Path(objects_dir) / "incoming"
    target_dir.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".blob-write-", dir=str(target_dir))
    temporary = Path(temporary_name)
    compressor = zlib.compressobj()
    try:
        with os.fdopen(descriptor, "wb") as destination, open(file_path, "rb") as source:
            destination.write(compressor.compress(header))
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                destination.write(compressor.compress(chunk))
            destination.write(compressor.flush())

        sha = digest.hexdigest()
        final_path = object_path(objects_dir, sha)
        final_path.parent.mkdir(parents=True, exist_ok=True)
        if final_path.exists():
            temporary.unlink()
        else:
            os.replace(temporary, final_path)
    finally:
        if temporary.exists():
            temporary.unlink()
        try:
            target_dir.rmdir()
        except OSError:
            pass
    return sha, size


def read_object(
    objects_dir: os.PathLike[str] | str,
    sha: str,
    expected_type: Optional[bytes] = None,
) -> Tuple[bytes, bytes]:
    """Read an object, returning ``(type_bytes, content_bytes)``."""
    path = object_path(objects_dir, sha)
    try:
        with open(path, "rb") as handle:
            content = zlib.decompress(handle.read())
    except FileNotFoundError:
        raise ObjectError(f"object not found: {sha}") from None
    except zlib.error as exc:
        raise ObjectError(f"corrupt object {sha}: {exc}") from None

    null = content.find(b"\0")
    if null < 0:
        raise ObjectError(f"corrupt object {sha}: missing header")
    header, data = content[:null], content[null + 1 :]
    try:
        object_type, size_text = header.split(b" ", 1)
        size = int(size_text)
    except ValueError:
        raise ObjectError(f"corrupt object {sha}: bad header") from None
    if size != len(data):
        raise ObjectError(f"corrupt object {sha}: size mismatch")
    if object_type not in (OBJECT_BLOB, OBJECT_TREE, OBJECT_COMMIT):
        raise ObjectError(f"unknown object type {object_type!r}")
    if expected_type is not None and object_type != expected_type:
        raise ObjectError(f"object {sha} has type {object_type.decode()!r}, expected {expected_type.decode()!r}")
    return object_type, data


def read_blob(objects_dir: os.PathLike[str] | str, sha: str) -> bytes:
    return read_object(objects_dir, sha, OBJECT_BLOB)[1]


def serialize_tree(entries: Iterable[TreeEntry]) -> bytes:
    ordered = sorted(entries, key=lambda entry: entry.name.encode("utf-8"))
    result = bytearray()
    for entry in ordered:
        if not entry.mode or not entry.name or "\x00" in entry.name or "/" in entry.name:
            raise ObjectError(f"invalid tree entry name: {entry.name!r}")
        if len(entry.hash) != 40:
            raise ObjectError(f"invalid tree entry hash: {entry.hash!r}")
        result.extend(entry.mode.encode("ascii"))
        result.extend(b" ")
        result.extend(entry.name.encode("utf-8"))
        result.append(0)
        result.extend(bytes.fromhex(entry.hash))
    return bytes(result)


def parse_tree(data: bytes) -> list[TreeEntry]:
    entries: list[TreeEntry] = []
    position = 0
    while position < len(data):
        null = data.find(b"\0", position)
        if null < 0:
            raise ObjectError("truncated tree entry header")
        header = data[position:null]
        try:
            mode, name = header.split(b" ", 1)
        except ValueError:
            raise ObjectError("invalid tree entry header") from None
        hash_end = null + 21
        if hash_end > len(data):
            raise ObjectError("truncated tree entry hash")
        raw_hash = data[null + 1 : hash_end]
        entries.append(TreeEntry(mode.decode("ascii"), name.decode("utf-8"), raw_hash.hex()))
        position = hash_end
    return entries


def write_tree_from_index(
    objects_dir: os.PathLike[str] | str,
    entries: Mapping[str, Tuple[str, str]],
) -> str:
    """Build all directory trees from flat ``path -> (mode, blob_hash)`` entries."""
    tree: Dict[str, object] = {}
    for path_str, item in entries.items():
        path = path_str.replace("\\", "/").strip("/")
        parts = path.split("/")
        if not path or path == "." or any(part in ("", ".", "..") for part in parts):
            raise ObjectError(f"invalid indexed path: {path_str!r}")
        node = tree
        for directory in parts[:-1]:
            next_node = node.setdefault(directory, {})
            if not isinstance(next_node, dict):
                raise ObjectError(f"path conflicts with file: {directory}")
            node = next_node
        name = parts[-1]
        if name in node:
            raise ObjectError(f"duplicate tree path: {path}")
        node[name] = ("blob", item[0], item[1])

    def build(node: Dict[str, object]) -> str:
        tree_entries: list[TreeEntry] = []
        for name, value in sorted(node.items(), key=lambda kv: kv[0].encode("utf-8")):
            if isinstance(value, dict):
                tree_entries.append(TreeEntry(TREE_MODE, name, build(value)))
            else:
                _, mode, blob_hash = value  # type: ignore[misc]
                tree_entries.append(TreeEntry(mode, name, blob_hash))
        return write_object(objects_dir, OBJECT_TREE, serialize_tree(tree_entries))

    return build(tree)


def read_tree_flat(
    objects_dir: os.PathLike[str] | str,
    tree_hash: Optional[str],
    prefix: str = "",
) -> Dict[str, Tuple[str, str]]:
    if not tree_hash:
        return {}
    result: Dict[str, Tuple[str, str]] = {}

    def walk(current_hash: str, current_prefix: str) -> None:
        for entry in parse_tree(read_object(objects_dir, current_hash, OBJECT_TREE)[1]):
            path = f"{current_prefix}{entry.name}"
            if entry.mode == TREE_MODE:
                walk(entry.hash, path + "/")
            else:
                result[path] = (entry.mode, entry.hash)

    walk(tree_hash, prefix)
    return result
