"""High-level implementations of minigit subcommands."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Optional

from . import commits, diff as diff_module, index as index_module, objects, refs, status as status_module
from .commits import Commit
from .errors import MinigitError, UsageError
from .ignore import IgnoreRules
from .repository import Repository, find_repository
from .workspace import restore_tree, update_index_from_worktree


def open_repo() -> Repository:
    return find_repository().require()


def cmd_init(path: Optional[str] = None) -> int:
    root = Path(path or os.getcwd())
    root.mkdir(parents=True, exist_ok=True)
    repo = Repository(root)
    existed = repo.init()
    print(f"Initialized minigit repository in {repo.git_dir}")
    return 0 if not existed else 0


def _rules(repo: Repository) -> IgnoreRules:
    return IgnoreRules.from_file(repo.ignore_file)


def cmd_add(paths: list[str]) -> int:
    if not paths:
        raise UsageError("add requires at least one path")
    repo = open_repo()
    try:
        update_index_from_worktree(repo, paths, _rules(repo))
    except FileNotFoundError as exc:
        raise MinigitError(str(exc)) from None
    return 0


def _head_tree(repo: Repository) -> tuple[Optional[str], dict[str, tuple[str, str]]]:
    head = refs.head_commit(repo)
    if not head:
        return None, {}
    commit = commits.read_commit(repo.objects_dir, head)
    return head, objects.read_tree_flat(repo.objects_dir, commit.tree)


def cmd_commit(message: Optional[str] = None, allow_empty: bool = False) -> int:
    if message is None or not message.strip():
        raise UsageError("commit requires a non-empty message with -m <message>")
    repo = open_repo()
    entries = index_module.read_index(repo.index_file)
    parent, head_tree = _head_tree(repo)
    if entries == head_tree and not allow_empty:
        print("nothing to commit; working index equals HEAD (no empty commit created)")
        return 1
    tree_hash = objects.write_tree_from_index(repo.objects_dir, entries)
    author_name = os.environ.get("MINIGIT_AUTHOR_NAME") or os.environ.get("GIT_AUTHOR_NAME") or "minigit"
    author_email = os.environ.get("MINIGIT_AUTHOR_EMAIL") or os.environ.get("GIT_AUTHOR_EMAIL") or "minigit@localhost"
    timezone = time.strftime("%z") or "+0000"
    commit = Commit(
        tree=tree_hash,
        parents=[parent] if parent else [],
        author=f"{author_name} <{author_email}>",
        author_time=int(time.time()),
        author_tz=timezone,
        message=message.rstrip() + "\n",
    )
    commit_hash = commits.write_commit(repo.objects_dir, commit)
    refs.write_branch(repo, refs.current_branch(repo), commit_hash)
    branch = refs.current_branch(repo)
    print(f"[{branch} {commit_hash[:7]}] {message.splitlines()[0]}")
    return 0


def cmd_log(oneline: bool = False, revision: Optional[str] = None) -> int:
    repo = open_repo()
    start = refs.resolve_commit(repo, revision)
    if not start:
        print("Repository has no commits yet.")
        return 1
    for sha, commit in commits.chain(repo.objects_dir, start):
        first_line = commit.message.splitlines()[0] if commit.message.strip() else ""
        if oneline:
            print(f"{sha[:7]} {first_line}")
        else:
            print(f"commit {sha}")
            print(f"Author: {commit.author}")
            print(f"Date:   {commits.format_commit_date(commit)}")
            print()
            print("\n".join("    " + line for line in commit.message.rstrip("\n").splitlines()))
            print()
    return 0


def cmd_branch(name: Optional[str] = None) -> int:
    repo = open_repo()
    if name is None:
        current = refs.current_branch(repo)
        names = refs.list_branches(repo)
        for branch in names:
            marker = "*" if branch == current else " "
            print(f"{marker} {branch}")
        if not names:
            print(f"  (no branches yet; current unborn branch: {current})")
        return 0
    if refs.read_branch(repo, name):
        raise MinigitError(f"branch already exists: {name}")
    head = refs.head_commit(repo)
    if not head:
        raise MinigitError("cannot create a branch before the first commit")
    refs.write_branch(repo, name, head)
    return 0


def cmd_checkout(branch: Optional[str]) -> int:
    if branch is None:
        raise UsageError("checkout requires a branch name")
    repo = open_repo()
    target_commit_hash = refs.read_branch(repo, branch)
    if target_commit_hash is None:
        raise MinigitError(f"branch does not exist: {branch}")
    current = refs.current_branch(repo)
    if branch == current:
        print(f"Already on '{branch}'")
        return 0

    target_commit = commits.read_commit(repo.objects_dir, target_commit_hash)
    target_tree = objects.read_tree_flat(repo.objects_dir, target_commit.tree)
    index = index_module.read_index(repo.index_file)
    rules = _rules(repo)
    status_items = status_module.calculate_status(repo, objects.read_tree_flat(repo.objects_dir, _safe_commit_tree(repo, refs.head_commit(repo))), index, rules)
    for rel, item in status_items.items():
        if item.worktree in ("M", "D") and rel in target_tree:
            raise MinigitError(f"local changes would be overwritten by checkout: {rel}")
        if item.worktree == "?":
            target = repo.root / rel.rstrip("/")
            if rel in target_tree:
                raise MinigitError(f"untracked file would be overwritten by checkout: {rel}")
            if target.is_dir() and _target_inside_directory(rel, target_tree):
                raise MinigitError(f"untracked directory would be overwritten by checkout: {rel}")

    restore_tree(repo, target_tree, list(set(index) | set(target_tree)))
    index_module.write_index(repo.index_file, target_tree)
    refs.switch_branch(repo, branch)
    print(f"Switched to branch '{branch}'")
    return 0


def _safe_commit_tree(repo: Repository, commit_hash: Optional[str]) -> Optional[str]:
    if not commit_hash:
        return None
    return commits.read_commit(repo.objects_dir, commit_hash).tree


def _target_inside_directory(directory_rel: str, tree: dict[str, tuple[str, str]]) -> bool:
    prefix = directory_rel.rstrip("/") + "/"
    return any(path.startswith(prefix) for path in tree)


def cmd_status(short: bool = False) -> int:
    repo = open_repo()
    branch = refs.current_branch(repo)
    _, head_tree = _head_tree(repo)
    entries = index_module.read_index(repo.index_file)
    items = status_module.calculate_status(repo, head_tree, entries, _rules(repo))
    if short:
        output = status_module.format_short_status(items)
        if output:
            print(output)
    else:
        print(status_module.format_long_status(items, branch))
    return 0


def cmd_diff(cached: bool = False, stat: bool = False, revision: Optional[str] = None) -> int:
    repo = open_repo()
    index = index_module.read_index(repo.index_file)
    head, head_tree = _head_tree(repo)
    if cached:
        if revision:
            target_commit_hash = refs.resolve_commit(repo, revision)
            if not target_commit_hash:
                old_tree = {}
            else:
                target_commit = commits.read_commit(repo.objects_dir, target_commit_hash)
                old_tree = objects.read_tree_flat(repo.objects_dir, target_commit.tree)
        else:
            old_tree = head_tree
        output, stats = diff_module.make_diff(repo, old_tree, index, new_from_worktree=False)
    elif revision:
        target_commit_hash = refs.resolve_commit(repo, revision)
        if not target_commit_hash:
            raise MinigitError(f"unknown commit reference: {revision}")
        target_commit = commits.read_commit(repo.objects_dir, target_commit_hash)
        old_tree = objects.read_tree_flat(repo.objects_dir, target_commit.tree)
        output, stats = diff_module.make_diff(repo, old_tree, index, new_from_worktree=True)
    else:
        output, stats = diff_module.make_diff(repo, index, index, new_from_worktree=True)
    print(diff_module.format_stat(stats) if stat else output, end="")
    return 0


def cmd_reset(mode: Optional[str], revision: Optional[str]) -> int:
    if mode not in ("--soft", "--mixed"):
        raise UsageError("reset requires --soft <commit> or --mixed <commit>")
    if not revision:
        raise UsageError("reset requires a commit reference")
    repo = open_repo()
    target_hash = refs.resolve_commit(repo, revision)
    if not target_hash:
        raise MinigitError(f"unknown commit reference: {revision}")
    # Validate it is a commit object.
    target_commit = commits.read_commit(repo.objects_dir, target_hash)
    branch = refs.current_branch(repo)
    refs.write_branch(repo, branch, target_hash)
    if mode == "--mixed":
        target_tree = objects.read_tree_flat(repo.objects_dir, target_commit.tree)
        index_module.write_index(repo.index_file, target_tree)
    return 0
