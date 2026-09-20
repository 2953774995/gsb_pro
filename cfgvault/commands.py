"""High-level cfgvault subcommand implementations."""

from __future__ import annotations

import getpass
import os
import time
from typing import List, Optional, Sequence

from .diff import diff_versions, render_diff
from .errors import CfgvaultError, InvalidArgumentError, InvalidReferenceError
from .index import Index, IndexEntry, read_index, write_index
from .objects import (
    Snapshot,
    build_tree,
    flatten_tree,
    read_snapshot,
    write_snapshot,
    write_tree_from_entries,
)
from .refs import (
    branch_exists,
    create_branch,
    list_branches,
    read_branch_oid,
    read_head_name,
    read_head_oid,
    resolve_snapshot,
    set_head_name,
    update_branch,
    validate_branch_name,
)
from .repo import Repository, init_repository
from .workspace import add_paths, compute_status, restore_tree


def _empty_tree(repo: Repository) -> str:
    """Write/read the canonical empty tree for empty snapshots or checkouts."""
    oid = write_tree_from_entries(repo, ())
    return oid


def _author_identity() -> str:
    name = os.environ.get("CFGVULT_AUTHOR_NAME") or os.environ.get("USER") or getpass.getuser()
    email = os.environ.get("CFGVULT_AUTHOR_EMAIL") or f"{name}@cfgvault.local"
    safe_name = name.replace("\n", " ").strip() or "operator"
    safe_email = email.replace("\n", " ").strip() or "operator@cfgvault.local"
    return f"{safe_name} <{safe_email}>"


def _current_date() -> str:
    override = os.environ.get("CFGVULT_AUTHOR_DATE")
    if override:
        # Deterministic tests may provide either a Unix timestamp or a ready
        # RFC-like string.
        if override.isdigit():
            value = time.localtime(int(override))
        else:
            return override
    else:
        value = time.localtime()
    offset_seconds = -time.timezone if value.tm_isdst <= 0 else -time.altzone
    sign = "+" if offset_seconds >= 0 else "-"
    offset_seconds = abs(offset_seconds)
    offset_text = f"{sign}{offset_seconds // 3600:02d}{(offset_seconds % 3600) // 60:02d}"
    return time.strftime("%Y-%m-%d %H:%M:%S ", value) + offset_text


def cmd_init(path: Optional[str] = None) -> str:
    repo = init_repository(path)
    return f"Initialized empty cfgvault repository in {repo.dir}"


def cmd_add(paths: Sequence[str]) -> str:
    from .repo import find_repository

    repo = find_repository()
    add_paths(repo, list(paths))
    return ""


def cmd_snap(message: str) -> str:
    """Create a snapshot from the current index and advance the current branch.

    A no-change snap is deliberately permitted and creates a new snapshot
    object.  Its tree hash equals the parent's tree (or the empty tree before
    the first snap), but parent/date/operator/message still make the historical
    point explicit. This keeps behavior predictable for auditors.
    """
    from .repo import find_repository

    repo = find_repository()
    message = (message or "").strip()
    if not message:
        raise InvalidArgumentError("usage: cfgvault snap -m <message>")
    index = read_index(repo)
    tree_oid = build_tree(repo, index.blob_map()) if len(index) else _empty_tree(repo)
    parent = read_head_oid(repo)
    snapshot = Snapshot(
        tree=tree_oid,
        parent=parent,
        author=_author_identity(),
        date=_current_date(),
        message=message,
    )
    oid = write_snapshot(repo, snapshot)
    update_branch(repo, read_head_name(repo), oid)
    return f"[{read_head_name(repo)} {oid}] {message.splitlines()[0]}"


def _log_line(repo: Repository, oid: str, oneline: bool) -> str:
    snapshot = read_snapshot(repo, oid)
    subject = snapshot.message.splitlines()[0] if snapshot.message.splitlines() else ""
    if oneline:
        return f"{oid[:8]} {subject}"
    return (
        f"snapshot {oid}\n"
        f"operator: {snapshot.author}\n"
        f"date:     {snapshot.date}\n"
        f"subject:  {subject}"
    )


def cmd_log(oneline: bool = False, start_ref: Optional[str] = None) -> str:
    from .repo import find_repository

    repo = find_repository()
    current = resolve_snapshot(repo, start_ref) if start_ref else read_head_oid(repo)
    if current is None:
        return ""
    blocks: List[str] = []
    seen = set()
    while current:
        if current in seen:
            raise CfgvaultError("corrupt snapshot history: parent cycle detected")
        seen.add(current)
        blocks.append(_log_line(repo, current, oneline))
        parent = read_snapshot(repo, current).parent
        current = parent
    separator = "\n" if oneline else "\n\n"
    return separator.join(blocks)


def cmd_branch(name: Optional[str] = None) -> str:
    from .repo import find_repository

    repo = find_repository()
    if name is None:
        current = read_head_name(repo)
        lines = []
        for branch in list_branches(repo):
            lines.append(("* " if branch == current else "  ") + branch)
        return "\n".join(lines)

    validate_branch_name(name)
    if branch_exists(repo, name):
        raise InvalidArgumentError(f"branch already exists: {name}")
    create_branch(repo, name, read_head_oid(repo))
    return f"created branch {name}"


def cmd_checkout(name: str) -> str:
    from .repo import find_repository

    repo = find_repository()
    if not name:
        raise InvalidArgumentError("usage: cfgvault checkout <branch>")
    validate_branch_name(name)
    if not branch_exists(repo, name):
        raise InvalidReferenceError(f"branch does not exist: {name}")
    current = read_head_name(repo)
    if current == name:
        return f"Already on branch {name}"

    old_index = read_index(repo)
    target_oid = read_branch_oid(repo, name, required=True)
    target_tree = read_snapshot(repo, target_oid).tree if target_oid else _empty_tree(repo)
    # Restore first so an unsafe untracked-file collision aborts before HEAD
    # moves. restore_tree updates the index only after a successful materialize.
    restore_tree(repo, target_tree, previous_paths=set(old_index.paths()))
    set_head_name(repo, name)
    return f"Switched to branch {name}"


def _short_state(staged: Optional[str], worktree: Optional[str], untracked: bool, ignored: bool) -> str:
    if ignored and untracked:
        return "!!"
    if untracked:
        return "??"
    x = {
        "added": "A",
        "modified": "M",
        "deleted": "D",
    }.get(staged, " ")
    y = {
        "modified": "M",
        "deleted": "D",
    }.get(worktree, " ")
    return x + y


def cmd_status(short: bool = False) -> str:
    from .repo import find_repository

    repo = find_repository()
    branch = read_head_name(repo)
    statuses = compute_status(repo)
    visible = [item for item in statuses if not (item.untracked and item.ignored)]

    if short:
        lines = [f"## {branch}"]
        for item in visible:
            code = _short_state(item.staged, item.worktree, item.untracked, item.ignored)
            if code.strip():
                lines.append(f"{code} {item.path}")
        return "\n".join(lines) + ("\n" if lines else "")

    groups = {
        "staged": [item for item in visible if item.staged],
        "worktree": [item for item in visible if item.worktree],
        "untracked": [item for item in visible if item.untracked and not item.ignored],
    }
    lines = [f"On branch {branch}"]
    if any(groups.values()):
        if groups["staged"]:
            lines.append("\nChanges to be committed:")
            for item in groups["staged"]:
                lines.append(f"  {item.staged}: {item.path}")
        if groups["worktree"]:
            lines.append("\nChanges not staged for snapshot:")
            for item in groups["worktree"]:
                lines.append(f"  {item.worktree}: {item.path}")
        if groups["untracked"]:
            lines.append("\nUntracked files:")
            for item in groups["untracked"]:
                lines.append(f"  {item.path}")
    else:
        lines.append("\nnothing to snapshot, working tree clean")
    return "\n".join(lines)


def cmd_diff(
    cached: bool = False,
    stat: bool = False,
    refs: Sequence[str] = (),
) -> str:
    from .repo import find_repository

    repo = find_repository()
    if len(refs) > 2:
        raise InvalidArgumentError("usage: cfgvault diff [--cached] [--stat] [<snapshot> [<snapshot>]]")
    old_ref = refs[0] if len(refs) >= 1 else None
    new_ref = refs[1] if len(refs) >= 2 else None
    results = diff_versions(repo, cached=cached, old_ref=old_ref, new_ref=new_ref)
    return render_diff(results, stat=stat)


def cmd_reset(mode: str, snapshot_ref: Optional[str]) -> str:
    from .repo import find_repository

    repo = find_repository()
    if mode not in ("soft", "mixed"):
        raise InvalidArgumentError("usage: cfgvault reset (--soft|--mixed) <snapshot>")
    if not snapshot_ref:
        raise InvalidArgumentError("usage: cfgvault reset (--soft|--mixed) <snapshot>")
    target = resolve_snapshot(repo, snapshot_ref)
    branch = read_head_name(repo)
    update_branch(repo, branch, target)
    if mode == "mixed":
        snapshot = read_snapshot(repo, target)
        index = Index()
        for path, (entry_mode, blob_oid) in sorted(flatten_tree(repo, snapshot.tree).items()):
            index.add(IndexEntry(path, entry_mode, blob_oid))
        write_index(repo, index)
    return f"reset ({mode}) {branch} to {target}"
