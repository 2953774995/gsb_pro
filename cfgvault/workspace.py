"""Working-tree traversal and snapshot restoration."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Dict, Iterator

from .errors import CfgvaultError
from .ignore import IgnoreRules, _CONFIG_DIR_NAME
from .index import write_index
from .objects import file_mode, hash_blob_file, write_blob_file
from .trees import IndexEntry


def portable_path(rel: Path) -> str:
    return rel.as_posix()


def safe_relpath(root: Path, path: Path) -> Path:
    try:
        resolved_root = root.resolve()
        resolved_path = path.resolve()
        rel = resolved_path.relative_to(resolved_root)
    except (OSError, ValueError) as exc:
        raise CfgvaultError(f"path is outside repository: {path}") from exc
    return rel


def _ignored_directory_without_tracked(
    rel_dir: str, rules: IgnoreRules, entries: Dict[str, IndexEntry]
) -> bool:
    prefix = "" if rel_dir == "." else rel_dir + "/"
    if rel_dir != "." and rules.matches(rel_dir, is_dir=True):
        return not any(path.startswith(prefix) for path in entries)
    if prefix == "":
        return False
    # A matching parent directory also ignores descendants.
    for part_path in _ancestors(rel_dir):
        if rules.matches(part_path, is_dir=True):
            return not any(path.startswith(prefix) for path in entries)
    return False


def _ancestors(path: str) -> Iterator[str]:
    parts = path.split("/")
    for i in range(1, len(parts) + 1):
        yield "/".join(parts[:i])


def iter_work_files(
    root: Path,
    rules: IgnoreRules,
    tracked_entries: Dict[str, IndexEntry] | None = None,
    base: Path | None = None,
) -> Iterator[tuple[Path, str, bool]]:
    """Yield ``(absolute_path, portable_relpath, tracked)`` in stable order.

    Directories ignored by rules are pruned, except when they contain already
    tracked files (so deletions and modifications remain visible).
    """
    tracked_entries = tracked_entries or {}
    start = (base or root)
    if start != root:
        rel_start = safe_relpath(root, start)
    else:
        rel_start = Path(".")
    stack: list[Path] = [start]
    while stack:
        directory = stack.pop()
        rel_dir = "." if directory == root else directory.relative_to(root).as_posix()
        if directory != root:
            parts = directory.relative_to(root).parts
            if _CONFIG_DIR_NAME in parts or ".git" in parts:
                continue
        if _ignored_directory_without_tracked(rel_dir, rules, tracked_entries):
            continue
        try:
            children = list(directory.iterdir())
        except FileNotFoundError:
            continue
        children.sort(key=lambda p: p.name.encode("utf-8"), reverse=True)
        for child in children:
            rel = child.relative_to(root).as_posix()
            if (
                rel == _CONFIG_DIR_NAME
                or rel.startswith(_CONFIG_DIR_NAME + "/")
                or rel == ".git"
                or rel.startswith(".git/")
                or "/.git/" in rel
                or rel.endswith("/.git")
            ):
                continue
            is_tracked = rel in tracked_entries
            if child.is_symlink():
                raise CfgvaultError(f"symbolic links are not supported: {rel}")
            if child.is_dir():
                if rules.matches(rel, is_dir=True) and not any(
                    path.startswith(rel + "/") for path in tracked_entries
                ):
                    continue
                stack.append(child)
            elif child.is_file():
                if not is_tracked and rules.matches(rel, is_dir=False):
                    continue
                yield child, rel, is_tracked


def scan_work_files(
    root: Path, rules: IgnoreRules, tracked_entries: Dict[str, IndexEntry] | None = None
) -> Dict[str, Path]:
    return {rel: path for path, rel, _tracked in iter_work_files(root, rules, tracked_entries)}


def add_path(
    root: Path,
    path: Path,
    entries: Dict[str, IndexEntry],
    rules: IgnoreRules,
) -> tuple[Dict[str, IndexEntry], list[str]]:
    """Add one file/directory and stage deletions for tracked missing paths."""
    result = dict(entries)
    added: list[str] = []
    abs_path = path if path.is_absolute() else root / path
    if not abs_path.exists():
        rel = safe_relpath(root, abs_path).as_posix()
        if rel in result:
            del result[rel]
            added.append(rel)
        else:
            raise CfgvaultError(f"path does not exist: {path}")
        return result, added
    if abs_path.is_symlink():
        raise CfgvaultError(f"symbolic links are not supported: {path}")
    if abs_path.is_file():
        rel = safe_relpath(root, abs_path).as_posix()
        if rel == ".cfgvaultignore" or rel in result or not rules.matches(rel, is_dir=False):
            oid = write_blob_file(root, abs_path)
            result[rel] = IndexEntry(mode=file_mode(abs_path), oid=oid)
            added.append(rel)
        return result, added
    if abs_path.is_dir():
        rel_dir = safe_relpath(root, abs_path).as_posix()
        parts = [part for part in rel_dir.split("/") if part]
        if _CONFIG_DIR_NAME in parts or ".git" in parts:
            raise CfgvaultError("repository metadata directories can never be tracked")
        for child_path, rel, tracked in iter_work_files(root, rules, result, base=abs_path):
            if not tracked and rules.matches(rel, is_dir=False):
                continue
            oid = write_blob_file(root, child_path)
            result[rel] = IndexEntry(mode=file_mode(child_path), oid=oid)
            added.append(rel)
        prefix = "" if rel_dir == "." else rel_dir + "/"
        existing_under = [p for p in result if not prefix or p.startswith(prefix)]
        disk_files = {rel for _, rel, _ in iter_work_files(root, rules, result, base=abs_path)}
        for rel in existing_under:
            if rel not in disk_files:
                del result[rel]
                added.append(rel)
        return result, added
    raise CfgvaultError(f"unsupported path type: {path}")


def _remove_empty_parent_dirs(root: Path, path: Path) -> None:
    parent = path.parent
    root_resolved = root.resolve()
    while parent != parent.parent and parent.resolve() != root_resolved:
        try:
            parent.rmdir()
        except OSError:
            return
        parent = parent.parent


def restore_worktree(
    root: Path,
    target_entries: Dict[str, IndexEntry],
    old_entries: Dict[str, IndexEntry],
    blob_loader,
) -> None:
    """Restore target tracked files while preserving unrelated untracked files."""
    old_paths = set(old_entries)
    target_paths = set(target_entries)

    # Validate before mutating: an untracked file at a future target path, or a
    # regular file blocking a target directory, must not be silently replaced.
    for rel in sorted(target_paths):
        path = root / rel
        if path.exists() and rel not in old_paths:
            raise CfgvaultError(
                f"refusing to overwrite untracked file with checkout target: {rel}"
            )
        parent = path.parent
        rel_parent = parent.relative_to(root).as_posix()
        while parent != root:
            if parent.exists() and parent.is_file() and rel_parent not in old_paths:
                raise CfgvaultError(
                    f"refusing to replace untracked file with checkout directory: {rel_parent}"
                )
            parent = parent.parent
            rel_parent = Path(rel_parent).parent.as_posix()

    for rel in sorted(old_paths - target_paths):
        path = root / rel
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        _remove_empty_parent_dirs(root, path)

    for rel in sorted(target_paths):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        data = blob_loader(target_entries[rel].oid)
        fd, tmp_name = tempfile.mkstemp(prefix=".cfgvault-work-", dir=str(path.parent))
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            os.chmod(tmp_path, int(target_entries[rel].mode[-3:], 8))
            os.replace(tmp_path, path)
        except BaseException:
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass
            raise

    write_index(root, target_entries)
