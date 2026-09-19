"""Working-tree traversal, content comparison, and checkout operations."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple

from . import objects
from .ignore import IgnoreRules
from .repository import Repository


def file_mode(path: Path) -> str:
    return objects.EXECUTABLE_MODE if path.stat().st_mode & 0o111 else objects.FILE_MODE


def is_within(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def relative_path(root: Path, path: Path) -> str:
    return str(path.resolve().relative_to(root.resolve())).replace(os.sep, "/")


def walk_files(root: Path, rules: IgnoreRules, base: Path | None = None) -> list[str]:
    """List regular files under root, returned relative to ``base`` (default root)."""
    root = root.resolve()
    base = (base or root).resolve()
    result: list[str] = []

    def scan(directory: Path, prefix: str) -> None:
        try:
            children = sorted(directory.iterdir(), key=lambda p: p.name)
        except (FileNotFoundError, PermissionError):
            return
        for child in children:
            rel = f"{prefix}{child.name}" if prefix else child.name
            absolute_rel = relative_path(base, child) if child.exists() else rel
            if absolute_rel == ".minigit" or absolute_rel.startswith(".minigit/"):
                continue
            try:
                is_directory = child.is_dir()
                is_file = child.is_file()
            except OSError:
                continue
            if is_directory:
                if rules.is_ignored(absolute_rel, True):
                    continue
                scan(child, rel + "/")
            elif is_file:
                if not rules.is_ignored(absolute_rel, False):
                    result.append(absolute_rel)

    scan(root, "")
    return sorted(result, key=lambda p: p.encode("utf-8"))


def hash_worktree_file(root: Path, rel_path: str) -> Tuple[str, str]:
    path = root / rel_path
    blob_hash, _size = objects.write_blob_from_path(objects_dir=root / ".minigit" / "objects", file_path=path)
    return file_mode(path), blob_hash


def update_index_from_worktree(repo: Repository, requested: Iterable[str], rules: IgnoreRules) -> Dict[str, Tuple[str, str]]:
    from .index import read_index, update_entries, write_index

    index = read_index(repo.index_file)
    changes: Dict[str, Tuple[str, str] | None] = {}
    for value in requested:
        original = Path(value)
        path = original if original.is_absolute() else Path.cwd() / original
        if not is_within(repo.root, path):
            raise FileNotFoundError(f"path is outside repository: {value}")
        if path.exists():
            resolved_path = path.resolve()
            if resolved_path == repo.root:
                rel = "."
            else:
                rel = relative_path(repo.root, resolved_path)
        else:
            rel = str(original).replace("\\", "/")
        if path.is_dir():
            root_directory = rel == "."
            directory_prefix = "" if root_directory else rel.rstrip("/") + "/"
            for candidate in walk_files(path, rules, repo.root):
                changes[candidate] = hash_worktree_file(repo.root, candidate)
            for tracked_path in index:
                if root_directory or tracked_path == rel or tracked_path.startswith(directory_prefix):
                    if not (repo.root / tracked_path).exists():
                        changes[tracked_path] = None
        elif path.is_file():
            # Explicit requests can add an ignored file if it is already tracked;
            # ordinary .minigitignore behavior remains skip-for-status/new add.
            if rules.is_ignored(rel, False) and rel not in index:
                continue
            changes[rel] = hash_worktree_file(repo.root, rel)
        elif rel in index:
            changes[rel] = None
        else:
            raise FileNotFoundError(f"path does not exist: {value}")

    updated = update_entries(index, changes)
    write_index(repo.index_file, updated)
    return updated


def has_file_changes(root: Path, index: Dict[str, Tuple[str, str]]) -> Dict[str, Optional[Tuple[str, str]]]:
    result: Dict[str, Optional[Tuple[str, str]]] = {}
    for rel, item in index.items():
        path = root / rel
        if not path.is_file():
            result[rel] = None
        else:
            try:
                current = hash_worktree_file(root, rel)
            except OSError:
                result[rel] = None
            else:
                if current != item:
                    result[rel] = current
    return result


def remove_empty_parents(root: Path, path: Path) -> None:
    current = path.parent
    root_resolved = root.resolve()
    while current != root_resolved:
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


def restore_tree(repo: Repository, tree_entries: Dict[str, Tuple[str, str]], tracked: Iterable[str]) -> None:
    """Check out a tree, preserving unrelated untracked files."""
    tracked_set = set(tracked)
    target_set = set(tree_entries)

    for rel in sorted(tracked_set - target_set, key=lambda p: p.encode("utf-8"), reverse=True):
        path = repo.root / rel
        try:
            if path.is_file() or path.is_symlink():
                path.unlink()
                remove_empty_parents(repo.root, path)
        except FileNotFoundError:
            pass

    for rel, (mode, blob_hash) in sorted(tree_entries.items(), key=lambda kv: kv[0].encode("utf-8")):
        path = repo.root / rel
        if path.exists() and path.is_dir() and not path.is_symlink():
            raise FileExistsError(f"cannot restore file {rel}: untracked directory is in the way")
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise FileExistsError(f"cannot restore {rel}: unsupported existing filesystem entry")
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists() or hash_worktree_file(repo.root, rel) != (mode, blob_hash):
            with open(path, "wb") as handle:
                handle.write(objects.read_blob(repo.objects_dir, blob_hash))
        os.chmod(path, 0o755 if mode == objects.EXECUTABLE_MODE else 0o644)
