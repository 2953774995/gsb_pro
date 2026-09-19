"""Simplified unified textual diffs and --stat summaries."""

from __future__ import annotations

import difflib
from pathlib import Path
from typing import Dict, Iterable, Mapping, Tuple

from . import objects
from .repository import Repository


def is_binary(data: bytes) -> bool:
    return b"\0" in data[:8192]


def split_lines(data: bytes) -> list[str]:
    text = data.decode("utf-8", errors="surrogateescape")
    return text.splitlines(keepends=True)


def line_stats(old: bytes, new: bytes) -> Tuple[int, int]:
    if old == new:
        return 0, 0
    if is_binary(old) or is_binary(new):
        return 0, 0
    matcher = difflib.SequenceMatcher(None, split_lines(old), split_lines(new))
    inserted = deleted = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("replace", "delete"):
            deleted += i2 - i1
        if tag in ("replace", "insert"):
            inserted += j2 - j1
    return inserted, deleted


def unified_diff_file(path: str, old: bytes, new: bytes) -> list[str]:
    if old == new:
        return []
    if is_binary(old) or is_binary(new):
        return [f"Binary files a/{path} and b/{path} differ\n"]
    lines = list(
        difflib.unified_diff(
            split_lines(old),
            split_lines(new),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            n=3,
        )
    )
    return lines


def changed_files(left: Mapping[str, Tuple[str, str]], right: Mapping[str, Tuple[str, str]]) -> list[str]:
    return sorted(set(left) | set(right), key=lambda path: path.encode("utf-8"))


def load_tree_bytes(repo: Repository, entries: Mapping[str, Tuple[str, str]], path: str) -> bytes:
    if path not in entries:
        return b""
    return objects.read_blob(repo.objects_dir, entries[path][1])


def load_worktree_bytes(repo: Repository, entries: Mapping[str, Tuple[str, str]], path: str) -> bytes:
    full = repo.root / path
    if not full.is_file():
        return b""
    return full.read_bytes()


def make_diff(repo: Repository, old_entries, new_entries, new_from_worktree: bool = False) -> tuple[str, list[tuple[str, int, int]]]:
    output: list[str] = []
    stats: list[tuple[str, int, int]] = []
    for path in changed_files(old_entries, new_entries):
        old_bytes = load_tree_bytes(repo, old_entries, path)
        if new_from_worktree and path in new_entries:
            new_bytes = load_worktree_bytes(repo, new_entries, path)
        elif path in new_entries:
            new_bytes = load_tree_bytes(repo, new_entries, path)
        else:
            new_bytes = b""
        if old_bytes == new_bytes:
            continue
        additions, deletions = line_stats(old_bytes, new_bytes)
        stats.append((path, additions, deletions))
        output.extend(unified_diff_file(path, old_bytes, new_bytes))
    return "".join(output), stats


def format_stat(stats: Iterable[Tuple[str, int, int]]) -> str:
    stats = list(stats)
    if not stats:
        return ""
    width = max((len(path) for path, _, _ in stats), default=0)
    total_insertions = 0
    total_deletions = 0
    changed_files = 0
    lines = []
    for path, inserted, deleted in stats:
        total_insertions += inserted
        total_deletions += deleted
        changed_files += 1
        changes = inserted + deleted
        bar = "+" * min(inserted, 40) + "-" * min(deleted, 40)
        lines.append(f" {path.ljust(width)} | {changes:3d} {bar}")
    summary_parts = []
    if changed_files:
        noun = "file" if changed_files == 1 else "files"
        summary_parts.append(f"{changed_files} {noun} changed")
    if total_insertions:
        noun = "insertion" if total_insertions == 1 else "insertions"
        summary_parts.append(f"{total_insertions} {noun}(+)")
    if total_deletions:
        noun = "deletion" if total_deletions == 1 else "deletions"
        summary_parts.append(f"{total_deletions} {noun}(-)")
    lines.append(" " + ", ".join(summary_parts))
    return "\n".join(lines)
