"""Command implementations for cfgvault.

Each command accepts parsed argparse attributes and returns a process exit code.
All user-facing diagnostics go through the CLI's error handler; commands here
raise :class:`CfgvaultError` for expected operational failures.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict

from .diff import FileStat, compare_entries, format_stat
from .errors import InvalidReferenceError
from .objects import file_mode, hash_blob_file
from .refs import (
    branch_exists,
    create_branch,
    list_branches,
    read_branch,
    update_branch,
    write_head,
)
from .repository import Repository, init_repository
from .snapshots import create_snapshot, read_snapshot
from .trees import IndexEntry, read_tree
from .workspace import add_path, restore_worktree, scan_work_files


def cmd_init(args: argparse.Namespace, out) -> int:
    root = init_repository(Path(args.path).resolve() if args.path else None)
    print(f"Initialized empty cfgvault repository in {root / '.cfgvault'}", file=out)
    return 0


def cmd_add(args: argparse.Namespace, out) -> int:
    repo = Repository.discover()
    rules = repo.rules()
    entries = repo.index()
    changed: list[str] = []
    for raw_path in args.paths:
        path = Path(raw_path)
        if not path.is_absolute():
            path = Path.cwd() / path
        entries, paths = add_path(repo.root, path.resolve(), entries, rules)
        changed.extend(paths)
    repo.write_index(entries)
    if changed:
        for path in sorted(set(changed)):
            print(f"staged {path}", file=out)
    else:
        print("No changes were staged", file=out)
    return 0


def _head_entries(repo: Repository) -> Dict[str, IndexEntry]:
    return repo.head_tree_entries()


def cmd_snap(args: argparse.Namespace, out) -> int:
    repo = Repository.discover()
    branch = repo.branch_name()
    entries = repo.index()
    parent = repo.head_snapshot()
    head_entries = _head_entries(repo)

    if entries == head_entries and not args.allow_empty:
        print("No changes staged; snapshot not created", file=out)
        return 0

    tree_oid = repo.build_tree(entries)
    oid = create_snapshot(
        repo.root,
        tree_oid,
        args.message,
        parent=parent,
        operator=args.operator,
        timestamp=args.date,
    )
    update_branch(repo.root, branch, oid)
    print(f"[{branch} {oid[:8]}] {args.message.strip().splitlines()[0]}", file=out)
    return 0


def cmd_log(args: argparse.Namespace, out) -> int:
    repo = Repository.discover()
    snapshot = repo.head_snapshot()
    if not snapshot:
        print("No snapshots yet", file=out)
        return 0
    seen: set[str] = set()
    first = True
    while snapshot:
        if snapshot in seen:
            raise CfgvaultError(f"snapshot parent cycle detected at {snapshot}")
        seen.add(snapshot)
        data = read_snapshot(repo.root, snapshot)
        if args.oneline:
            first_line = data["message"].splitlines()[0]
            print(f"{snapshot[:8]} {first_line}", file=out)
        else:
            if not first:
                print(file=out)
            first = False
            print(f"snapshot {snapshot}", file=out)
            print(f"operator: {data['operator']}", file=out)
            print(f"date:     {data['date']}", file=out)
            print(f"message:  {data['message']}", file=out)
        snapshot = data.get("parent")
    return 0


def cmd_branch(args: argparse.Namespace, out) -> int:
    repo = Repository.discover()
    if not args.name:
        current = repo.branch_name()
        branches = list_branches(repo.root)
        if not branches:
            print("No branches yet", file=out)
        for name in branches:
            marker = "*" if name == current else " "
            print(f"{marker} {name}", file=out)
        return 0
    if branch_exists(repo.root, args.name):
        raise InvalidReferenceError(f"branch already exists: {args.name}")
    create_branch(repo.root, args.name, repo.head_snapshot())
    print(f"created branch {args.name}", file=out)
    return 0


def cmd_checkout(args: argparse.Namespace, out) -> int:
    repo = Repository.discover()
    name = args.branch
    if not branch_exists(repo.root, name):
        raise InvalidReferenceError(f"branch does not exist: {name}")
    current = repo.branch_name()
    if name == current:
        print(f"Already on branch {name}", file=out)
        return 0
    target_snapshot = read_branch(repo.root, name)
    target_entries = read_tree(repo.root, read_snapshot(repo.root, target_snapshot)["tree"]) if target_snapshot else {}
    old_entries = repo.index()
    restore_worktree(repo.root, target_entries, old_entries, repo.read_blob)
    write_head(repo.root, name)
    print(f"Switched to branch {name}", file=out)
    return 0


def _work_index_entries(repo: Repository, rules) -> tuple[Dict[str, IndexEntry], Dict[str, bytes]]:
    """Hash current files without putting every work-only blob in storage."""
    entries = repo.index()
    files = scan_work_files(repo.root, rules, entries)
    work_entries: Dict[str, IndexEntry] = {}
    data_by_oid: Dict[str, bytes] = {}
    for rel, path in sorted(files.items()):
        oid = hash_blob_file(path)
        work_entries[rel] = IndexEntry(mode=file_mode(path), oid=oid)
        data_by_oid[oid] = path.read_bytes()
    return work_entries, data_by_oid


def _load_diff_blob(repo: Repository, extra: Dict[str, bytes]):
    def loader(oid: str) -> bytes:
        if oid in extra:
            return extra[oid]
        return repo.read_blob(oid)

    return loader


def _status_entries(repo: Repository):
    rules = repo.rules()
    index = repo.index()
    head = _head_entries(repo)
    files = scan_work_files(repo.root, rules, index)
    return rules, index, head, files


def cmd_status(args: argparse.Namespace, out) -> int:
    repo = Repository.discover()
    branch = repo.branch_name()
    index, head, files = (lambda t: (t[1], t[2], t[3]))(_status_entries(repo))
    # Keep rule loading side effects conceptually present even if unused.
    staged_added = sorted(p for p in set(index) - set(head))
    staged_removed = sorted(p for p in set(head) - set(index))
    staged_modified = sorted(
        p for p in set(index) & set(head)
        if (index[p].oid, index[p].mode) != (head[p].oid, head[p].mode)
    )
    work_modified: list[str] = []
    work_deleted: list[str] = []
    for path, entry in sorted(index.items()):
        disk = files.get(path)
        if disk is None:
            work_deleted.append(path)
        else:
            disk_oid = hash_blob_file(disk)
            if disk_oid != entry.oid or file_mode(disk) != entry.mode:
                work_modified.append(path)
    untracked = sorted(set(files) - set(index))

    if args.short:
        print(f"## {branch}", file=out)
        for p in staged_added:
            print(f"A  {p}", file=out)
        for p in staged_modified:
            print(f"M  {p}", file=out)
        for p in staged_removed:
            print(f"D  {p}", file=out)
        for p in work_modified:
            print(f" M {p}", file=out)
        for p in work_deleted:
            print(f" D {p}", file=out)
        for p in untracked:
            print(f"?? {p}", file=out)
        if not any((staged_added, staged_modified, staged_removed, work_modified, work_deleted, untracked)):
            print("clean working tree", file=out)
        return 0

    print(f"On branch {branch}", file=out)
    printed_section = False
    if staged_added or staged_modified or staged_removed:
        printed_section = True
        print("\nChanges to be committed (staged):", file=out)
        for p in staged_added:
            kind = "new file" if p not in head else "modified"
            print(f"  {kind}: {p}", file=out)
        for p in staged_modified:
            print(f"  modified: {p}", file=out)
        for p in staged_removed:
            print(f"  deleted:  {p}", file=out)
    if work_modified or work_deleted:
        printed_section = True
        print("\nChanges not staged (working tree vs index):", file=out)
        for p in work_modified:
            print(f"  modified: {p}", file=out)
        for p in work_deleted:
            print(f"  deleted:  {p}", file=out)
    if untracked:
        printed_section = True
        print("\nUntracked files:", file=out)
        for p in untracked:
            print(f"  {p}", file=out)
    if not printed_section:
        print("Nothing to snapshot; working tree clean", file=out)
    return 0


def _entries_for_ref(repo: Repository, ref: str) -> Dict[str, IndexEntry]:
    snapshot = repo.resolve_snapshot(ref)
    data = read_snapshot(repo.root, snapshot)
    return read_tree(repo.root, data["tree"])


def _emit_diff(text: str, stats: list[FileStat], stat_only: bool, out) -> int:
    if stat_only:
        formatted = format_stat(stats)
        if formatted:
            print(formatted, end="", file=out)
        else:
            print(" 0 files changed", file=out)
    elif text:
        print(text, end="", file=out)
    else:
        print("No differences", file=out)
    return 0


def cmd_diff(args: argparse.Namespace, out) -> int:
    repo = Repository.discover()
    extra: Dict[str, bytes] = {}
    if len(args.refs) == 2:
        old_entries = _entries_for_ref(repo, args.refs[0])
        new_entries = _entries_for_ref(repo, args.refs[1])
    elif args.cached:
        old_entries = _head_entries(repo)
        new_entries = repo.index()
    elif args.head:
        old_entries = _head_entries(repo)
        new_entries, extra = _work_index_entries(repo, repo.rules())
    elif len(args.refs) == 1:
        old_entries = _entries_for_ref(repo, args.refs[0])
        new_entries, extra = _work_index_entries(repo, repo.rules())
    else:
        old_entries = repo.index()
        new_entries, extra = _work_index_entries(repo, repo.rules())
    text, stats = compare_entries(old_entries, new_entries, _load_diff_blob(repo, extra))
    return _emit_diff(text, stats, args.stat, out)


def cmd_reset(args: argparse.Namespace, out) -> int:
    repo = Repository.discover()
    target = repo.resolve_snapshot(args.snapshot)
    # read_snapshot validates that the target really is a snapshot.
    read_snapshot(repo.root, target)
    update_branch(repo.root, repo.branch_name(), target)
    if args.mode == "mixed":
        data = read_snapshot(repo.root, target)
        repo.write_index(read_tree(repo.root, data["tree"]))
    print(f"branch {repo.branch_name()} reset to {target[:8]} ({args.mode})", file=out)
    return 0
