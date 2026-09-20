"""Simplified unified-diff generation and per-file statistics."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Callable, Dict, List, Optional, Tuple

from .index import Index, read_index
from .objects import flatten_tree, read_blob, read_snapshot, hash_blob_file
from .refs import read_head_oid, resolve_snapshot
from .repo import Repository, worktree_path

BlobMap = Dict[str, Tuple[str, str, Callable[[], bytes]]]


@dataclass(frozen=True)
class DiffResult:
    path: str
    binary: bool = False
    added: int = 0
    deleted: int = 0
    text: str = ""


def _stored_blob_map(repo: Repository, tree_oid: Optional[str]) -> BlobMap:
    result: BlobMap = {}
    if tree_oid is None:
        return result
    for path, (mode, oid) in flatten_tree(repo, tree_oid).items():
        result[path] = (mode, oid, lambda oid=oid: read_blob(repo, oid))
    return result


def _index_blob_map(repo: Repository, index: Index) -> BlobMap:
    result: BlobMap = {}
    for entry in index.entries():
        result[entry.path] = (entry.mode, entry.oid, lambda oid=entry.oid: read_blob(repo, oid))
    return result





def _all_worktree_files_map(repo: Repository) -> BlobMap:
    """Hash visible, non-ignored files in the worktree.

    This includes untracked files for worktree comparisons. The files are only
    hashed here; ``add`` remains the operation that stores blob objects.
    """
    from .workspace import iter_worktree_files

    result: BlobMap = {}
    for path, mode in iter_worktree_files(repo, include_ignored=False):
        full = worktree_path(repo, path)
        oid, _ = hash_blob_file(full)

        def loader(full: str = full) -> bytes:
            with open(full, "rb") as stream:
                return stream.read()

        result[path] = (mode, oid, loader)
    return result


def _is_binary(data: bytes) -> bool:
    return b"\x00" in data[:8192]


def _decode_lines(data: bytes) -> List[str]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        # Treat unknown encodings as binary; cfgvault is aimed at JSON text.
        raise BinaryContent
    return text.splitlines(keepends=True)


class BinaryContent(Exception):
    pass


def _unified_range(start: int, count: int) -> str:
    # Unified diff starts line numbers at 1 and uses no count when it is 1.
    # A zero-length range conventionally displays position 0.
    if count == 0:
        return f"{start},0"
    if count == 1:
        return str(start)
    return f"{start},{count}"




def render_text_diff(path: str, old_data: bytes, new_data: bytes, context: int = 3) -> DiffResult:
    try:
        old_lines = _decode_lines(old_data)
        new_lines = _decode_lines(new_data)
    except BinaryContent:
        return DiffResult(path=path, binary=True)
    if old_lines == new_lines:
        return DiffResult(path=path)

    matcher = SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    groups = list(matcher.get_grouped_opcodes(context))
    output = [f"diff --cfgvault a/{path} b/{path}\n"]
    added = 0
    deleted = 0

    for group in groups:
        first_i1, first_i2, first_j1, first_j2 = group[0][1:]
        old_start = first_i1 + 1 if first_i2 > first_i1 else first_i1
        new_start = first_j1 + 1 if first_j2 > first_j1 else first_j1
        old_count = group[-1][2] - group[0][1]
        new_count = group[-1][4] - group[0][3]
        output.append(
            f"@@ -{_unified_range(old_start, old_count)} +{_unified_range(new_start, new_count)} @@\n"
        )
        for tag, i1, i2, j1, j2 in group:
            if tag in ("delete", "replace"):
                for line in old_lines[i1:i2]:
                    output.append("-" + line)
                    deleted += 1
                    if not line.endswith("\n"):
                        output.append("\\ No newline at end of file\n")
            if tag in ("insert", "replace"):
                for line in new_lines[j1:j2]:
                    output.append("+" + line)
                    added += 1
                    if not line.endswith("\n"):
                        output.append("\\ No newline at end of file\n")
            if tag == "equal":
                for line in old_lines[i1:i2]:
                    output.append(" " + line)
                    if not line.endswith("\n"):
                        output.append("\\ No newline at end of file\n")

    return DiffResult(path=path, added=added, deleted=deleted, text="".join(output))


def _render_binary(path: str) -> DiffResult:
    return DiffResult(path=path, binary=True)


def compare_maps(old_map: BlobMap, new_map: BlobMap, loader_side: Optional[str] = None) -> List[DiffResult]:
    results = []
    for path in sorted(set(old_map) | set(new_map)):
        old_entry = old_map.get(path)
        new_entry = new_map.get(path)
        if old_entry and new_entry and old_entry[1] == new_entry[1] and old_entry[0] == new_entry[0]:
            continue
        old_data = old_entry[2]() if old_entry else b""
        new_data = new_entry[2]() if new_entry else b""
        if old_data == new_data:
            continue
        if _is_binary(old_data) or _is_binary(new_data):
            results.append(_render_binary(path))
        else:
            results.append(render_text_diff(path, old_data, new_data))
    return results


def _snapshot_tree(repo: Repository, expression: Optional[str]) -> Optional[str]:
    if expression is None:
        return None
    return read_snapshot(repo, resolve_snapshot(repo, expression)).tree


def diff_versions(
    repo: Repository,
    cached: bool = False,
    old_ref: Optional[str] = None,
    new_ref: Optional[str] = None,
) -> List[DiffResult]:
    """Build the requested comparison.

    Positional forms mirror common expectations:

    * no args       -> worktree versus index (default);
    * ``--cached``  -> index versus HEAD;
    * one snapshot  -> worktree versus snapshot;
    * two snapshots  -> first snapshot versus second snapshot.
    """
    index = read_index(repo)
    if cached and old_ref is None and new_ref is None:
        head_oid = read_head_oid(repo)
        head_tree = read_snapshot(repo, head_oid).tree if head_oid else None
        return compare_maps(_stored_blob_map(repo, head_tree), _index_blob_map(repo, index))

    if old_ref is None and new_ref is None:
        return compare_maps(_index_blob_map(repo, index), _all_worktree_files_map(repo))

    if new_ref is None:
        target_tree = _snapshot_tree(repo, old_ref)
        target = _stored_blob_map(repo, target_tree)
        return compare_maps(target, _all_worktree_files_map(repo))

    old = _stored_blob_map(repo, _snapshot_tree(repo, old_ref))
    new = _stored_blob_map(repo, _snapshot_tree(repo, new_ref))
    return compare_maps(old, new)


def render_diff(results: List[DiffResult], stat: bool = False) -> str:
    changed = [result for result in results if result.binary or result.added or result.deleted or result.text]
    if stat:
        lines = []
        total_add = total_delete = 0
        max_name = max((len(result.path) for result in changed), default=0)
        for result in changed:
            total_add += result.added
            total_delete += result.deleted
            change_count = result.added + result.deleted
            bars = "+" * min(result.added, 20) + "-" * min(result.deleted, 20)
            if result.binary:
                lines.append(f"{result.path.ljust(max_name)} | binary")
            else:
                lines.append(
                    f"{result.path.ljust(max_name)} | {change_count:4d}  +{result.added} -{result.deleted} {bars}"
                )
        if changed:
            files_word = "file" if len(changed) == 1 else "files"
            lines.append(
                f"{len(changed)} {files_word} changed, {total_add} insertion(s)(+), {total_delete} deletion(s)(-)"
            )
        return "\n".join(lines) + ("\n" if lines else "")

    chunks = []
    for result in changed:
        if result.binary:
            chunks.append(f"Binary files a/{result.path} and b/{result.path} differ\n")
        else:
            chunks.append(result.text)
    return "".join(chunks)
