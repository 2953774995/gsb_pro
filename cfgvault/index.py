"""Stable binary index used to register staged files."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Optional

from .errors import InvalidObjectError
from .objects import validate_oid
from .repo import Repository
from .util import atomic_write_bytes, normalize_relpath, read_bytes

INDEX_MAGIC = b"CFGVLTIDX\n"
INDEX_VERSION = b"1\n"
REGULAR_MODES = frozenset(("100644", "100755"))


@dataclass(frozen=True)
class IndexEntry:
    """A staged path, its mode, and its blob object id."""

    path: str
    mode: str
    oid: str


class Index:
    """Path-ordered in-memory representation of ``.cfgvault/index``."""

    def __init__(self, entries: Optional[Iterable[IndexEntry]] = None):
        self._entries: Dict[str, IndexEntry] = {}
        for entry in entries or ():
            self.add(entry)

    def add(self, entry: IndexEntry) -> None:
        path = normalize_relpath(entry.path)
        if entry.mode not in REGULAR_MODES:
            raise InvalidObjectError(f"unsupported index mode for {path}: {entry.mode}")
        validate_oid(entry.oid)
        self._entries[path] = IndexEntry(path, entry.mode, entry.oid)

    def remove(self, path: str) -> bool:
        return self._entries.pop(normalize_relpath(path), None) is not None

    def get(self, path: str) -> Optional[IndexEntry]:
        return self._entries.get(normalize_relpath(path))

    def __contains__(self, path: str) -> bool:
        return normalize_relpath(path) in self._entries

    def __len__(self) -> int:
        return len(self._entries)

    def entries(self) -> tuple[IndexEntry, ...]:
        return tuple(self._entries[name] for name in sorted(self._entries))

    def paths(self) -> tuple[str, ...]:
        return tuple(sorted(self._entries))

    def blob_map(self) -> Dict[str, tuple[str, str]]:
        return {entry.path: (entry.mode, entry.oid) for entry in self.entries()}

    def write(self, repo: Repository) -> None:
        data = bytearray()
        data.extend(INDEX_MAGIC)
        data.extend(INDEX_VERSION)
        for entry in self.entries():
            record = entry.mode + "\t" + entry.oid + "\t" + entry.path + "\n"
            data.extend(record.encode("utf-8"))
        atomic_write_bytes(repo.index_file, bytes(data))


def empty_index() -> Index:
    return Index()


def read_index(repo: Repository) -> Index:
    """Read and validate the repository index.

    Format (version 1, little-endian text for easy inspection)::

        CFGVLTIDX
        1
        <mode>\\t<40-char-sha1>\\t<posix/path>
        ...

    Records are always sorted by path, making the index reproducible.
    """
    try:
        data = read_bytes(repo.index_file)
    except FileNotFoundError:
        return Index()
    if not data:
        return Index()
    if not data.startswith(INDEX_MAGIC):
        raise InvalidObjectError("invalid index: missing CFGVLTIDX header")
    rest = data[len(INDEX_MAGIC) :]
    if not rest.startswith(INDEX_VERSION):
        raise InvalidObjectError("unsupported index version (expected 1)")
    body = rest[len(INDEX_VERSION) :]
    index = Index()
    for line_number, line in enumerate(body.splitlines(), start=1):
        if not line:
            continue
        parts = line.split(b"\t", 2)
        if len(parts) != 3:
            raise InvalidObjectError(f"invalid index record on line {line_number}")
        try:
            mode = parts[0].decode("ascii")
            oid = parts[1].decode("ascii")
            path = parts[2].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise InvalidObjectError(f"invalid index record on line {line_number}") from exc
        index.add(IndexEntry(path, mode, oid))
    return index


def write_index(repo: Repository, index: Index) -> None:
    index.write(repo)


def update_file_entry(index: Index, path: str, mode: str, oid: str) -> None:
    index.add(IndexEntry(path, mode, oid))


def remove_path(index: Index, path: str) -> bool:
    return index.remove(path)
