"""Stable, reproducible cfgvault index storage."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Dict

from .trees import IndexEntry

INDEX_VERSION = 1
INDEX_PATH = Path(".cfgvault") / "index"


def index_path(root: Path) -> Path:
    return root / INDEX_PATH


def empty_index() -> Dict[str, IndexEntry]:
    return {}


def normalize_entries(entries: Dict[str, IndexEntry]) -> Dict[str, IndexEntry]:
    for path in entries:
        parts = path.split("/")
        if not path or path.startswith("/") or "//" in path:
            raise ValueError(f"invalid index path: {path!r}")
        if not parts or any(part in ("", ".", "..") for part in parts):
            raise ValueError(f"invalid index path: {path!r}")
    return dict(sorted(entries.items(), key=lambda item: item[0].encode("utf-8")))


def serialize_index(entries: Dict[str, IndexEntry]) -> bytes:
    normalized = normalize_entries(entries)
    payload = {
        "version": INDEX_VERSION,
        "entries": [
            {"path": path, "mode": entry.mode, "blob": entry.oid}
            for path, entry in normalized.items()
        ],
    }
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)
    return (text + "\n").encode("utf-8")


def parse_index(data: bytes) -> Dict[str, IndexEntry]:
    if not data.strip():
        return {}
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid index JSON: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("version") != INDEX_VERSION:
        raise ValueError("invalid index: missing or unsupported version")
    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, list):
        raise ValueError("invalid index: entries must be a list")
    entries: Dict[str, IndexEntry] = {}
    for item in raw_entries:
        if not isinstance(item, dict):
            raise ValueError("invalid index entry")
        path = item.get("path")
        mode = item.get("mode")
        blob = item.get("blob")
        if not isinstance(path, str) or not isinstance(mode, str) or not isinstance(blob, str):
            raise ValueError(f"invalid index entry: {item!r}")
        if path in entries:
            raise ValueError(f"duplicate index path: {path}")
        entries[path] = IndexEntry(mode=mode, oid=blob)
    return normalize_entries(entries)


def write_index(root: Path, entries: Dict[str, IndexEntry]) -> None:
    destination = index_path(root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".index-", dir=str(destination.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(serialize_index(entries))
        os.replace(tmp_path, destination)
    except BaseException:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise


def read_index(root: Path) -> Dict[str, IndexEntry]:
    path = index_path(root)
    if not path.exists():
        return {}
    return parse_index(path.read_bytes())
