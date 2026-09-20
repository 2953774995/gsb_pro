"""Content-addressable object database.

Three object kinds are stored:

* ``blob``     -- raw configuration file bytes;
* ``tree``     -- deterministic directory listing (mode/name/hash);
* ``snapshot`` -- snapshot metadata, including its parent snapshot.

Every object's id is ``SHA-1(type + b'\\0' + content)``.  Compressed payloads
are stored as ``.cfgvault/objects/xx/38remaining``.  Blobs are hashed and
compressed in fixed-size chunks so multi-megabyte files do not require
multiple copies in memory.
"""

from __future__ import annotations

import hashlib
import os
import zlib
from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Tuple

from .errors import InvalidObjectError
from .repo import Repository
from .util import is_executable

BLOB = "blob"
TREE = "tree"
SNAPSHOT = "snapshot"
OID_LEN = 40
CHUNK_SIZE = 1024 * 1024
OBJECT_TYPES = frozenset((BLOB, TREE, SNAPSHOT))


def validate_oid(oid: str, expected_type: Optional[str] = None) -> str:
    if not isinstance(oid, str) or len(oid) != OID_LEN:
        raise InvalidObjectError(f"invalid object id (expected 40 hex chars): {oid!r}")
    try:
        int(oid, 16)
    except ValueError as exc:
        raise InvalidObjectError(f"invalid object id (non-hex): {oid!r}") from exc
    if expected_type is not None:
        # Object id alone does not encode type, so callers that know the type
        # can check after reading.  This helper keeps validation centralized.
        if expected_type not in OBJECT_TYPES:
            raise InvalidObjectError(f"unknown expected object type: {expected_type}")
    return oid


def object_path(repo: Repository, oid: str) -> str:
    validate_oid(oid)
    return os.path.join(repo.objects_dir, oid[:2], oid[2:])


def exists_object(repo: Repository, oid: str) -> bool:
    return os.path.isfile(object_path(repo, oid))


def _decompress_payload(data: bytes) -> bytes:
    try:
        return zlib.decompress(data)
    except zlib.error as exc:
        raise InvalidObjectError("object payload is not valid zlib data") from exc


def read_compressed_object_file(path: str) -> bytes:
    try:
        with open(path, "rb") as stream:
            compressed = stream.read()
    except FileNotFoundError as exc:
        raise InvalidObjectError(f"object not found: {path}") from exc
    return _decompress_payload(compressed)


def read_object(repo: Repository, oid: str, expected_type: Optional[str] = None) -> Tuple[str, bytes]:
    """Return ``(object_type, content_bytes)`` for an object id."""
    validate_oid(oid, expected_type)
    content = read_compressed_object_file(object_path(repo, oid))
    try:
        type_text, raw = content.split(b"\0", 1)
        object_type = type_text.decode("ascii")
    except (ValueError, UnicodeDecodeError) as exc:
        raise InvalidObjectError(f"object {oid} has a malformed header") from exc
    if object_type not in OBJECT_TYPES:
        raise InvalidObjectError(f"object {oid} has unknown type {object_type!r}")
    if expected_type is not None and object_type != expected_type:
        raise InvalidObjectError(
            f"object {oid} is a {object_type}, expected {expected_type}"
        )
    return object_type, raw


def write_object(repo: Repository, object_type: str, content: bytes) -> str:
    """Write any object and return its SHA-1 id.

    Existing identical objects are reused.  Because the id includes the object
    type and content, this function also provides deduplication.
    """
    if object_type not in OBJECT_TYPES:
        raise InvalidObjectError(f"cannot write unknown object type: {object_type}")
    payload = object_type.encode("ascii") + b"\0" + content
    oid = hashlib.sha1(payload).hexdigest()
    path = object_path(repo, oid)
    if os.path.exists(path):
        return oid

    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    compressed = zlib.compress(payload, level=6)
    temporary = path + ".tmp"
    with open(temporary, "wb") as stream:
        stream.write(compressed)
    os.replace(temporary, path)
    return oid


def hash_blob_file(path: str) -> Tuple[str, int]:
    """Hash a blob file without reading the whole file at once."""
    digest = hashlib.sha1()
    digest.update(BLOB.encode("ascii") + b"\0")
    size = 0
    with open(path, "rb") as stream:
        while True:
            chunk = stream.read(CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def write_blob_file(repo: Repository, path: str) -> Tuple[str, int]:
    """Add a regular file as a deduplicated blob using chunked I/O."""
    oid, size = hash_blob_file(path)
    if exists_object(repo, oid):
        return oid, size

    # Recompute directly into zlib without keeping an entire second copy.
    compressor = zlib.compressobj(level=6)
    digest = hashlib.sha1()
    digest.update(BLOB.encode("ascii") + b"\0")
    output_path = object_path(repo, oid)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    temporary = output_path + ".tmp"
    try:
        with open(path, "rb") as source, open(temporary, "wb") as target:
            target.write(compressor.compress(BLOB.encode("ascii") + b"\0"))
            while True:
                chunk = source.read(CHUNK_SIZE)
                if not chunk:
                    break
                digest.update(chunk)
                target.write(compressor.compress(chunk))
            target.write(compressor.flush())
        actual_oid = digest.hexdigest()
        if actual_oid != oid:
            raise InvalidObjectError(
                f"blob hash mismatch while writing {path}: expected {oid}, got {actual_oid}"
            )
        os.replace(temporary, output_path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    return oid, size


def write_blob_bytes(repo: Repository, data: bytes) -> str:
    return write_object(repo, BLOB, data)


def read_blob(repo: Repository, oid: str) -> bytes:
    object_type, raw = read_object(repo, oid, BLOB)
    return raw


@dataclass(frozen=True)
class TreeEntry:
    """One tree record: POSIX mode, entry name, and referenced object id."""

    mode: str
    name: str
    oid: str

    def as_line(self) -> bytes:
        return self.mode.encode("ascii") + b"\t" + self.name.encode("utf-8") + b"\t" + self.oid.encode("ascii")




def parse_tree(raw: bytes, oid: str = "") -> Tuple[TreeEntry, ...]:
    entries = []
    for line in raw.splitlines():
        if not line:
            continue
        parts = line.split(b"\t", 2)
        if len(parts) != 3:
            raise InvalidObjectError(f"tree object {oid} has malformed entry: {line!r}")
        mode_bytes, name_bytes, oid_bytes = parts
        try:
            mode = mode_bytes.decode("ascii")
            name = name_bytes.decode("utf-8")
            entry_oid = oid_bytes.decode("ascii")
        except UnicodeDecodeError as exc:
            raise InvalidObjectError(f"tree object {oid} has a non-text entry") from exc
        if mode not in ("100644", "100755", "40000"):
            # Directories are represented by nested trees and do not have a
            # stored directory mode in this simplified object format.
            raise InvalidObjectError(f"tree object {oid} has unsupported mode {mode!r}")
        if not name or "/" in name or name in (".", ".."):
            raise InvalidObjectError(f"tree object {oid} has invalid name {name!r}")
        validate_oid(entry_oid)
        entries.append(TreeEntry(mode, name, entry_oid))
    return tuple(entries)


def serialize_tree(entries: Iterable[TreeEntry]) -> bytes:
    """Serialize entries sorted lexicographically by name for stability."""
    ordered = sorted(entries, key=lambda entry: entry.name)
    names = [entry.name for entry in ordered]
    if len(names) != len(set(names)):
        raise InvalidObjectError("cannot build tree containing duplicate names")
    if not ordered:
        return b""
    return b"".join(entry.as_line() + b"\n" for entry in ordered)


def write_tree_from_entries(repo: Repository, entries: Iterable[TreeEntry]) -> str:
    return write_object(repo, TREE, serialize_tree(entries))


def read_tree(repo: Repository, oid: str) -> Tuple[TreeEntry, ...]:
    object_type, raw = read_object(repo, oid, TREE)
    return parse_tree(raw, oid)


def mode_for_path(path: str) -> str:
    return "100755" if is_executable(os.stat(path).st_mode) else "100644"


def build_tree(repo: Repository, path_to_blob: Dict[str, Tuple[str, str]]) -> str:
    """Recursively build tree objects from ``{path: (mode, blob_oid)}``.

    The resulting root tree's hash is stable for the same logical mapping,
    regardless of insertion order or filesystem traversal order.
    """
    nodes: Dict[str, Dict[str, Tuple[str, str]]] = {}

    def node_for(directory: str) -> Dict[str, Tuple[str, str]]:
        return nodes.setdefault(directory, {})

    for relpath, value in path_to_blob.items():
        normalized = relpath.strip("/")
        if not normalized:
            raise InvalidObjectError("tree contains an empty file name")
        parts = normalized.split("/")
        if any(part in ("", ".", "..") for part in parts):
            raise InvalidObjectError(f"tree contains invalid path: {relpath}")
        directory = ""
        for part in parts[:-1]:
            node = node_for(directory)
            if part in node and node[part][0] != "tree":
                raise InvalidObjectError(f"path conflicts between file and directory: {relpath}")
            node[part] = ("tree", "")
            directory = part if not directory else directory + "/" + part
        parent = node_for("/".join(parts[:-1]))
        name = parts[-1]
        if name in parent and parent[name][0] == "tree":
            raise InvalidObjectError(f"path conflicts between directory and file: {relpath}")
        mode, blob_oid = value
        if mode not in ("100644", "100755"):
            raise InvalidObjectError(f"unsupported blob mode: {mode}")
        object_type, _ = read_object(repo, blob_oid)
        if object_type != BLOB:
            raise InvalidObjectError(f"tree path {relpath} references {object_type}, expected blob")
        parent[name] = ("blob", mode + ":" + blob_oid)

    # Build deepest directories first.  Object ids make parent hashes depend
    # on child hashes, so ordering is naturally acyclic.
    tree_ids: Dict[str, str] = {}
    # An index with one or more files always has a root placeholder. For an
    # empty index, return the canonical empty-tree object directly.
    if not path_to_blob:
        return write_tree_from_entries(repo, ())

    for directory in sorted(nodes, key=lambda value: (value.count("/"), value), reverse=True):
        entries = []
        for name, item in nodes[directory].items():
            if item[0] == "tree":
                child_dir = name if not directory else directory + "/" + name
                entries.append(TreeEntry("40000", name, tree_ids[child_dir]))
            else:
                mode, blob_oid = item[1].split(":", 1)
                entries.append(TreeEntry(mode, name, blob_oid))
        tree_ids[directory] = write_tree_from_entries(repo, entries)
    return tree_ids[""]


def flatten_tree(
    repo: Repository,
    tree_oid: str,
    prefix: str = "",
) -> Dict[str, Tuple[str, str]]:
    """Recursively return ``{path: (mode, blob_oid)}`` for a root tree."""
    result: Dict[str, Tuple[str, str]] = {}
    for entry in read_tree(repo, tree_oid):
        path = entry.name if not prefix else prefix + "/" + entry.name
        if entry.mode == "40000":
            result.update(flatten_tree(repo, entry.oid, path))
        else:
            result[path] = (entry.mode, entry.oid)
    return result


@dataclass(frozen=True)
class Snapshot:
    tree: str
    parent: Optional[str]
    author: str
    date: str
    message: str


def serialize_snapshot(snapshot: Snapshot) -> bytes:
    if "\n" in snapshot.author:
        raise InvalidObjectError("snapshot author cannot contain a newline")
    if "\n" in snapshot.date:
        raise InvalidObjectError("snapshot date cannot contain a newline")
    validate_oid(snapshot.tree, TREE)
    if snapshot.parent is not None:
        validate_oid(snapshot.parent, SNAPSHOT)
    message = snapshot.message if snapshot.message.endswith("\n") else snapshot.message + "\n"
    lines = [
        f"tree {snapshot.tree}\n",
    ]
    if snapshot.parent:
        lines.append(f"parent {snapshot.parent}\n")
    lines.extend(
        [
            f"author {snapshot.author}\n",
            f"date {snapshot.date}\n",
            "\n",
            message.encode("utf-8"),
        ]
    )
    # Convert early strings while retaining message bytes.
    head = b"".join(line.encode("utf-8") if isinstance(line, str) else line for line in lines[:-1])
    return head + message.encode("utf-8")


def write_snapshot(repo: Repository, snapshot: Snapshot) -> str:
    return write_object(repo, SNAPSHOT, serialize_snapshot(snapshot))


def parse_snapshot(raw: bytes, oid: str = "") -> Snapshot:
    try:
        header, message = raw.split(b"\n\n", 1)
    except ValueError as exc:
        raise InvalidObjectError(f"snapshot object {oid} is missing its message separator") from exc

    tree = None
    parent = None
    author = None
    date = None
    for line in header.split(b"\n"):
        key, _, value = line.partition(b" ")
        if key == b"tree":
            tree = value.decode("ascii")
        elif key == b"parent":
            parent = value.decode("ascii")
        elif key == b"author":
            author = value.decode("utf-8")
        elif key == b"date":
            date = value.decode("utf-8")
        else:
            raise InvalidObjectError(f"snapshot object {oid} has unknown header {key!r}")
    if tree is None or author is None or date is None:
        raise InvalidObjectError(f"snapshot object {oid} is missing required headers")
    validate_oid(tree, TREE)
    if parent is not None:
        validate_oid(parent, SNAPSHOT)
    return Snapshot(tree=tree, parent=parent, author=author, date=date, message=message.decode("utf-8"))


def read_snapshot(repo: Repository, oid: str) -> Snapshot:
    object_type, raw = read_object(repo, oid, SNAPSHOT)
    return parse_snapshot(raw, oid)
