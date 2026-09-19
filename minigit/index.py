"""Stable binary index (staging area) format."""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Tuple

MAGIC = b"MNGIDX\x01"
HEADER = struct.Struct(">7sH")
ENTRY = struct.Struct(">H20sH")


@dataclass(frozen=True)
class IndexEntry:
    mode: str
    hash: str


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(".index.tmp")
    try:
        with open(temporary, "wb") as handle:
            handle.write(data)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def serialize_index(entries: Dict[str, IndexEntry] | Dict[str, Tuple[str, str]]) -> bytes:
    """Serialize entries deterministically by UTF-8 path ordering."""
    normalized: list[tuple[str, str, str]] = []
    for path, value in entries.items():
        if isinstance(value, IndexEntry):
            mode, blob_hash = value.mode, value.hash
        else:
            mode, blob_hash = value
        clean = path.replace("\\", "/").strip("/")
        if not clean or any(part in ("", ".", "..") for part in clean.split("/")):
            raise ValueError(f"invalid index path: {path!r}")
        if len(blob_hash) != 40:
            raise ValueError(f"invalid blob hash for {clean}")
        normalized.append((clean, mode, blob_hash))
    normalized.sort(key=lambda item: item[0].encode("utf-8"))

    out = bytearray(HEADER.pack(MAGIC, len(normalized)))
    for path, mode, blob_hash in normalized:
        raw_path = path.encode("utf-8")
        out.extend(ENTRY.pack(int(mode, 8), bytes.fromhex(blob_hash), len(raw_path)))
        out.extend(raw_path)
    return bytes(out)


def write_index(path: os.PathLike[str] | str, entries: Dict[str, Tuple[str, str]]) -> None:
    _atomic_write(Path(path), serialize_index(entries))


def read_index(path: os.PathLike[str] | str) -> Dict[str, Tuple[str, str]]:
    path = Path(path)
    if not path.exists():
        return {}
    data = path.read_bytes()
    if not data:
        return {}
    if len(data) < HEADER.size:
        raise ValueError("corrupt index: truncated header")
    magic, count = HEADER.unpack_from(data, 0)
    if magic != MAGIC:
        raise ValueError("corrupt index: bad magic number")
    entries: Dict[str, Tuple[str, str]] = {}
    position = HEADER.size
    for _ in range(count):
        if len(data) - position < ENTRY.size:
            raise ValueError("corrupt index: truncated entry")
        mode, hash_bytes, path_length = ENTRY.unpack_from(data, position)
        position += ENTRY.size
        end = position + path_length
        if end > len(data):
            raise ValueError("corrupt index: truncated path")
        raw_path = data[position:end]
        position = end
        path = raw_path.decode("utf-8")
        if not path or path in entries:
            raise ValueError(f"corrupt index: invalid duplicate path {path!r}")
        entries[path] = (f"{mode:06o}", hash_bytes.hex())
    if position != len(data):
        raise ValueError("corrupt index: trailing data")
    return entries


def update_entries(index: Dict[str, Tuple[str, str]], changes: Dict[str, Tuple[str, str] | None]) -> Dict[str, Tuple[str, str]]:
    updated = dict(index)
    for path, value in changes.items():
        path = path.replace("\\", "/").strip("/")
        if value is None:
            updated.pop(path, None)
        else:
            updated[path] = value
    return dict(sorted(updated.items(), key=lambda item: item[0].encode("utf-8")))
