"""Worktree traversal, ``add``, checkout restore, and status comparison."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from typing import Dict, Iterator, Optional

from .errors import CfgvaultError, InvalidArgumentError, InvalidStateError
from .ignore import IgnoreRules, load_ignore_rules
from .index import Index, IndexEntry, read_index, write_index
from .objects import build_tree, flatten_tree, hash_blob_file, mode_for_path, read_blob, write_blob_file
from .repo import CFG_DIR, Repository, relative_worktree_path, worktree_path
from .util import atomic_write_bytes, normalize_relpath


def iter_worktree_files(
    repo: Repository,
    ignore: Optional[IgnoreRules] = None,
    include_ignored: bool = True,
) -> Iterator[tuple[str, str]]:
    """Yield ``(relative_path, mode)`` for regular files.

    The ``.cfgvault`` metadata directory is never traversed. By default files
    beneath ignored directories are still yielded because an already tracked
    file must remain visible to status/add; callers use the returned/ignored
    metadata policy in :func:`scan_worktree` for untracked files.
    """
    if ignore is None:
        ignore = load_ignore_rules(repo)
    root = repo.root
    for current, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        rel_dir = os.path.relpath(current, root)
        if rel_dir == ".":
            rel_dir = ""
        normalized_dir = normalize_relpath(rel_dir) if rel_dir else ""

        # Sorted traversal is deterministic. Modifying dirnames in-place prunes
        # os.walk's recursive descent.
        dirnames.sort()
        kept_dirs = []
        for dirname in dirnames:
            if normalized_dir == "" and dirname == CFG_DIR:
                continue
            relpath = dirname if not normalized_dir else normalized_dir + "/" + dirname
            if ignore.is_ignored(relpath, is_dir=True) and not include_ignored:
                continue
            kept_dirs.append(dirname)
        dirnames[:] = kept_dirs

        filenames.sort()
        for filename in filenames:
            full = os.path.join(current, filename)
            if os.path.islink(full):
                raise CfgvaultError(f"cfgvault: symbolic links are not supported: {full}")
            if not os.path.isfile(full):
                continue
            relpath = filename if not normalized_dir else normalized_dir + "/" + filename
            if ignore.is_ignored(relpath, is_dir=False) and not include_ignored:
                continue
            yield relpath, mode_for_path(full)


def scan_worktree(repo: Repository) -> tuple[Dict[str, tuple[str, str]], set[str]]:
    """Return all regular file blobs and a set of ignored relative paths."""
    ignore = load_ignore_rules(repo)
    result: Dict[str, tuple[str, str]] = {}
    ignored: set[str] = set()
    for relpath, mode in iter_worktree_files(repo, ignore, include_ignored=True):
        if ignore.is_ignored(relpath, is_dir=False):
            ignored.add(relpath)
        full = worktree_path(repo, relpath)
        oid, _size = hash_blob_file(full)
        result[relpath] = (mode, oid)
    return result, ignored


def _resolve_add_argument(repo: Repository, argument: str) -> tuple[str, bool]:
    abs_path = os.path.abspath(os.path.join(os.getcwd(), argument))
    root = os.path.abspath(repo.root)
    try:
        common = os.path.commonpath([root, abs_path])
    except ValueError as exc:
        raise CfgvaultError(f"cfgvault: path is outside repository: {argument}") from exc
    if common != root:
        raise CfgvaultError(f"cfgvault: path is outside repository: {argument}")
    rel = relative_worktree_path(repo, abs_path)
    if not rel:
        rel = "."
    if rel != "." and rel.split("/", 1)[0] == CFG_DIR:
        raise InvalidArgumentError("the .cfgvault metadata directory can never be added")
    return rel, os.path.isdir(abs_path)


def add_paths(repo: Repository, arguments: list[str]) -> Index:
    """Add one or more files/directories, updating the staged index.

    If an explicit file path no longer exists, it is removed from the index
    (stage deletion). Directories are traversed recursively.
    """
    if not arguments:
        raise InvalidArgumentError("usage: cfgvault add <path> [<path> ...]")

    index = read_index(repo)
    old_paths = set(index.paths())
    ignore = load_ignore_rules(repo)
    seen: set[str] = set()

    for argument in arguments:
        relpath, is_directory = _resolve_add_argument(repo, argument)
        full = worktree_path(repo, relpath)
        if is_directory:
            if ignore.is_ignored(relpath, is_dir=True):
                continue
            matched = False
            for candidate, mode in iter_worktree_files(repo, ignore, include_ignored=False):
                # Restrict recursive traversal to the requested subtree.
                in_root = relpath == "."
                if in_root or candidate == relpath or candidate.startswith(relpath + "/"):
                    matched = True
                    candidate_full = worktree_path(repo, candidate)
                    oid, _ = write_blob_file(repo, candidate_full)
                    index.add(IndexEntry(candidate, mode, oid))
                    seen.add(candidate)
            if not matched and not os.path.isdir(full):
                raise CfgvaultError(f"cfgvault: path does not exist: {argument}")
            scope = "" if relpath == "." else relpath + "/"
            for old_path in old_paths:
                in_scope = relpath == "." or old_path == relpath or old_path.startswith(scope)
                if in_scope and old_path not in seen and not ignore.is_ignored(old_path, is_dir=False):
                    index.remove(old_path)
                    seen.add(old_path)
        else:
            if ignore.is_ignored(relpath, is_dir=False):
                continue
            if not os.path.lexists(full):
                index.remove(relpath)
                seen.add(relpath)
                continue
            if os.path.islink(full) or not os.path.isfile(full):
                raise CfgvaultError(f"cfgvault: not a regular file: {argument}")
            oid, _ = write_blob_file(repo, full)
            index.add(IndexEntry(relpath, mode_for_path(full), oid))
            seen.add(relpath)

    write_index(repo, index)
    return index


def write_file_with_parents(path: str, data: bytes, mode: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.lexists(path) and not os.path.isfile(path):
        raise CfgvaultError(f"cfgvault: cannot restore over non-regular path: {path}")
    atomic_write_bytes(path, data)
    os.chmod(path, 0o755 if mode == "100755" else 0o644)


def _remove_file(path: str) -> None:
    try:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    except FileNotFoundError:
        return
    os.unlink(path)


def _prune_empty_dirs(root: str, stop: str) -> None:
    current = root
    while os.path.abspath(current) != os.path.abspath(stop):
        try:
            os.rmdir(current)
        except OSError:
            return
        parent = os.path.dirname(current)
        if parent == current:
            return
        current = parent


def restore_tree(
    repo: Repository,
    tree_oid: str,
    previous_paths: Optional[set[str]] = None,
) -> None:
    """Materialize a tree in the worktree and reset the index.

    Tracked files absent from the target are deleted, tracked target files
    are overwritten, and untracked files are left untouched.
    """
    target = flatten_tree(repo, tree_oid)
    old_paths = set(previous_paths or set())
    # Only files which were tracked immediately before checkout are eligible
    # for deletion. Files absent from both the old index and target tree are
    # untracked worktree files and must be preserved.
    delete_paths = sorted(old_paths - set(target), reverse=True)

    # Preflight before deleting anything: a target-only path that already
    # exists in the worktree is untracked and must not be silently replaced.
    for relpath in target:
        full = worktree_path(repo, relpath)
        if relpath not in old_paths and os.path.lexists(full):
            raise InvalidStateError(
                f"refusing checkout: untracked path would be overwritten: {relpath}"
            )

    for relpath in delete_paths:
        full = worktree_path(repo, relpath)
        if os.path.isfile(full) and not os.path.islink(full):
            _remove_file(full)
        parent = os.path.dirname(full)
        _prune_empty_dirs(parent, repo.root)

    index = Index()
    for relpath, (mode, blob_oid) in sorted(target.items()):
        full = worktree_path(repo, relpath)
        write_file_with_parents(full, read_blob(repo, blob_oid), mode)
        index.add(IndexEntry(relpath, mode, blob_oid))
    write_index(repo, index)


@dataclass(frozen=True)
class PathStatus:
    path: str
    staged: Optional[str]  # added, modified, deleted
    worktree: Optional[str]  # modified, deleted
    untracked: bool = False
    ignored: bool = False


def head_tree_map(repo: Repository, head_oid: Optional[str]) -> Dict[str, tuple[str, str]]:
    if not head_oid:
        return {}
    # Import locally to avoid a module import cycle.
    from .objects import read_snapshot

    return flatten_tree(repo, read_snapshot(repo, head_oid).tree)


def compute_status(repo: Repository) -> list[PathStatus]:
    """Compare HEAD, index, and worktree, including untracked/ignored files."""
    from .refs import read_head_oid

    index = read_index(repo)
    head = head_tree_map(repo, read_head_oid(repo))
    work, ignored_paths = scan_worktree(repo)

    indexed = set(index.paths())
    head_paths = set(head)
    work_paths = set(work)

    statuses: list[PathStatus] = []
    for path in sorted(indexed | head_paths | work_paths):
        staged = None
        worktree = None
        untracked = False
        if path in indexed:
            entry = index.get(path)
            assert entry is not None
            index_value = (entry.mode, entry.oid)
            if path not in head_paths:
                staged = "added"
            elif head[path] != index_value:
                staged = "modified"
            if path not in work_paths:
                worktree = "deleted"
            elif work[path] != index_value:
                worktree = "modified"
        else:
            if path in head_paths:
                # An unindexed path also in HEAD means it was staged for
                # deletion; if absent from worktree it was deleted without add.
                staged = "deleted"
                if path in work_paths and work[path] != head[path]:
                    worktree = "modified"
                elif path in work_paths:
                    # Content exactly reverted after staged deletion.
                    worktree = None
            elif path in work_paths:
                untracked = True
        statuses.append(
            PathStatus(
                path=path,
                staged=staged,
                worktree=worktree,
                untracked=untracked,
                ignored=path in ignored_paths,
            )
        )
    return statuses


def tree_from_index(repo: Repository, index: Index) -> str:
    return build_tree(repo, index.blob_map())
