"""High-level repository facade tying storage, refs, and work tree together."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

from .errors import NotInitializedError
from .ignore import IgnoreRules, load_ignore_rules
from .index import read_index, write_index
from .objects import read_blob
from .refs import (
    DEFAULT_BRANCH,
    branches_dir,
    create_branch,
    current_branch,
    head_file,
    read_branch,
    update_branch,
    write_head,
)
from .snapshots import read_snapshot, resolve_snapshot
from .trees import IndexEntry, build_tree, empty_tree, read_tree


def is_repository(path: Path) -> bool:
    return (path / ".cfgvault" / "HEAD").is_file()


def find_repository(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if is_repository(candidate):
            return candidate
    raise NotInitializedError(
        "cfgvault repository not found (or any parent directory); run 'cfgvault init' first"
    )


def init_repository(path: Path | None = None) -> Path:
    root = (path or Path.cwd()).resolve()
    vault = root / ".cfgvault"
    (vault / "objects").mkdir(parents=True, exist_ok=True)
    (vault / "refs" / "heads").mkdir(parents=True, exist_ok=True)
    if not (vault / "index").exists():
        write_index(root, {})
    if not head_file(root).exists():
        write_head(root, DEFAULT_BRANCH)
    default_ref = branches_dir(root) / DEFAULT_BRANCH
    if not default_ref.exists():
        create_branch(root, DEFAULT_BRANCH, None)
    return root


class Repository:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        if not is_repository(self.root):
            raise NotInitializedError(
                "cfgvault repository not found; run 'cfgvault init' first"
            )

    @classmethod
    def discover(cls, start: Path | None = None) -> "Repository":
        return cls(find_repository(start))

    def rules(self) -> IgnoreRules:
        return load_ignore_rules(self.root)

    def index(self) -> dict[str, IndexEntry]:
        return read_index(self.root)

    def write_index(self, entries: dict[str, IndexEntry]) -> None:
        write_index(self.root, entries)

    def branch_name(self) -> str:
        return current_branch(self.root)

    def head_snapshot(self) -> Optional[str]:
        return read_branch(self.root, self.branch_name())

    def head_tree_entries(self) -> dict[str, IndexEntry]:
        snapshot = self.head_snapshot()
        if snapshot is None:
            return {}
        data = read_snapshot(self.root, snapshot)
        return read_tree(self.root, data["tree"])

    def tree_entries_for_snapshot(self, oid: str) -> dict[str, IndexEntry]:
        data = read_snapshot(self.root, oid)
        return read_tree(self.root, data["tree"])

    def resolve_snapshot(self, ref: str) -> str:
        resolved = resolve_snapshot(self.root, ref)
        if resolved is None:
            from .errors import InvalidReferenceError

            raise InvalidReferenceError(f"unknown snapshot reference: {ref}")
        return resolved

    def empty_tree(self) -> str:
        return empty_tree(self.root)

    def build_tree(self, entries: dict[str, IndexEntry]) -> str:
        return build_tree(self.root, entries)

    def read_blob(self, oid: str) -> bytes:
        return read_blob(self.root, oid)

    def update_current_branch(self, snapshot_oid: str) -> None:
        update_branch(self.root, self.branch_name(), snapshot_oid)
