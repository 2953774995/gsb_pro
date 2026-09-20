"""Deterministic tree object construction and parsing."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable

from .errors import CfgvaultError
from .objects import DIR_MODE, TREE, read_object, write_object

# A path is represented as its portable POSIX-style relative string.
IndexEntries = Dict[str, "TreeEntryLike"]


@dataclass(frozen=True, order=True)
class TreeEntry:
    """One tree entry: mode, name, object hash."""

    mode: str
    name: str
    oid: str


@dataclass(frozen=True)
class IndexEntry:
    mode: str
    oid: str


def _sort_key(name: str) -> bytes:
    return name.encode("utf-8")


def serialize_tree(entries: Iterable[TreeEntry]) -> bytes:
    """Serialize tree entries in stable UTF-8 byte order.

    Format (one line per entry)::

        <mode> <name>\\t<sha-1>
    """
    ordered = sorted(entries, key=lambda entry: _sort_key(entry.name))
    lines = []
    seen: set[str] = set()
    for entry in ordered:
        if entry.name in seen:
            raise CfgvaultError(f"duplicate tree entry name: {entry.name}")
        if not entry.name or "\n" in entry.name or "\t" in entry.name or "/" in entry.name:
            raise CfgvaultError(f"invalid tree entry name: {entry.name!r}")
        seen.add(entry.name)
        lines.append(f"{entry.mode} {entry.name}\t{entry.oid}".encode("utf-8"))
    return b"".join(line + b"\n" for line in lines)


def parse_tree(payload: bytes) -> list[TreeEntry]:
    entries: list[TreeEntry] = []
    for number, raw_line in enumerate(payload.splitlines(), start=1):
        try:
            line = raw_line.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CfgvaultError(f"malformed tree line {number}: invalid UTF-8") from exc
        if not line:
            continue
        try:
            mode_and_name, oid = line.split("\t", 1)
            mode, name = mode_and_name.split(" ", 1)
        except ValueError as exc:
            raise CfgvaultError(f"malformed tree entry on line {number}: {line!r}") from exc
        entries.append(TreeEntry(mode=mode, name=name, oid=oid))
    return entries


def build_tree(root: Path, entries: dict[str, IndexEntry]) -> str:
    """Recursively build all directory trees and return the root tree ID."""
    # Nodes map child name -> (mode, oid); directories are represented by a
    # dict node, files by an IndexEntry.
    root_node: dict[str, object] = {}

    for path, entry in sorted(entries.items(), key=lambda item: _sort_key(item[0])):
        parts = [part for part in path.split("/") if part]
        if len(parts) != len(path.split("/")) or not parts or any(part in (".", "..") for part in parts):
            raise CfgvaultError(f"invalid tracked path: {path!r}")
        node = root_node
        for part in parts[:-1]:
            existing = node.get(part)
            if existing is None:
                existing = {}
                node[part] = existing
            elif not isinstance(existing, dict):
                raise CfgvaultError(f"path conflict: {part} is both a file and directory")
            node = existing
        name = parts[-1]
        if name in node:
            raise CfgvaultError(f"path conflict: {path} is both a file and directory")
        node[name] = entry

    def materialize(node: dict[str, object]) -> str:
        tree_entries: list[TreeEntry] = []
        for name in sorted(node, key=_sort_key):
            value = node[name]
            if isinstance(value, dict):
                tree_entries.append(TreeEntry(DIR_MODE, name, materialize(value)))
            elif isinstance(value, IndexEntry):
                tree_entries.append(TreeEntry(value.mode, name, value.oid))
            else:  # pragma: no cover - guarded by construction
                raise CfgvaultError("internal tree construction error")
        return write_object(root, TREE, serialize_tree(tree_entries))

    return materialize(root_node)


def read_tree(root: Path, tree_oid: str) -> dict[str, IndexEntry]:
    """Flatten a tree recursively into ``{path: IndexEntry(mode, blob)}``."""
    result: dict[str, IndexEntry] = {}

    def walk(oid: str, prefix: str) -> None:
        object_type, payload = read_object(root, oid)
        if object_type != TREE:
            raise CfgvaultError(f"object {oid} is {object_type}, expected tree")
        for entry in parse_tree(payload):
            path = f"{prefix}{entry.name}"
            if entry.mode == DIR_MODE:
                walk(entry.oid, path + "/")
            else:
                result[path] = IndexEntry(mode=entry.mode, oid=entry.oid)

    walk(tree_oid, "")
    return result


def empty_tree(root: Path) -> str:
    """Return the shared empty tree ID, creating it if necessary."""
    return write_object(root, TREE, b"")
