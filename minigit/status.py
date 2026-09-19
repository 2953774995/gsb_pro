"""Working-tree and index status calculation/reporting."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

from . import objects
from .ignore import IgnoreRules
from .repository import Repository
from .workspace import file_mode


@dataclass(frozen=True)
class StatusItem:
    staged: str  # ' ', A, M, D
    worktree: str  # ' ', M, D, ?


def _same_head_index(head_item: Optional[Tuple[str, str]], index_item: Optional[Tuple[str, str]]) -> bool:
    return head_item == index_item


def calculate_status(
    repo: Repository,
    head_tree: Dict[str, Tuple[str, str]],
    index: Dict[str, Tuple[str, str]],
    rules: IgnoreRules,
) -> Dict[str, StatusItem]:
    result: Dict[str, StatusItem] = {}
    tracked = sorted(set(head_tree) | set(index), key=lambda p: p.encode("utf-8"))
    for rel in tracked:
        head_item = head_tree.get(rel)
        index_item = index.get(rel)
        if head_item == index_item:
            staged = " "
        elif head_item is None:
            staged = "A"
        elif index_item is None:
            staged = "D"
        else:
            staged = "M"

        worktree = " "
        if index_item is not None:
            path = repo.root / rel
            if not path.is_file():
                worktree = "D"
            else:
                try:
                    actual_mode = file_mode(path)
                    digest = objects.write_blob_from_path(repo.objects_dir, path)[0]
                except OSError:
                    worktree = "D"
                else:
                    if (actual_mode, digest) != index_item:
                        worktree = "M"
        if staged != " " or worktree != " ":
            result[rel] = StatusItem(staged, worktree)

    for rel in _untracked_paths(repo.root, index, rules):
        result[rel] = StatusItem(" ", "?")
    return dict(sorted(result.items(), key=lambda kv: kv[0].encode("utf-8")))


def _untracked_paths(root: Path, index: Dict[str, Tuple[str, str]], rules: IgnoreRules) -> list[str]:
    result: list[str] = []

    def scan(directory: Path, prefix: str) -> None:
        try:
            children = sorted(directory.iterdir(), key=lambda p: p.name.encode("utf-8"))
        except OSError:
            return
        for child in children:
            rel = f"{prefix}{child.name}" if prefix else child.name
            if rel == ".minigit":
                continue
            try:
                is_directory = child.is_dir()
                is_file = child.is_file()
            except OSError:
                continue
            if rules.is_ignored(rel, is_directory):
                continue
            if is_directory:
                if not _directory_contains_indexed_path(child, rel, index):
                    result.append(rel.rstrip("/") + "/")
                else:
                    scan(child, rel + "/")
            elif is_file and rel not in index:
                result.append(rel)

    scan(root, "")
    return result


def _directory_contains_indexed_path(directory: Path, rel_prefix: str, index: Dict[str, Tuple[str, str]]) -> bool:
    prefix = rel_prefix.rstrip("/") + "/"
    return any(path == rel_prefix.rstrip("/") or path.startswith(prefix) for path in index)


def format_long_status(items: Dict[str, StatusItem], branch: str) -> str:
    sections = [
        ("Changes to be committed:", "staged"),
        ("Changes not staged for commit:", "worktree"),
    ]
    labels = {"A": "new file", "D": "deleted", "M": "modified"}
    lines = [f"On branch {branch}"]
    for title, column in sections:
        selected = [(p, i) for p, i in items.items() if getattr(i, column) in labels and not (column == "worktree" and i.worktree == "?")]
        if selected:
            lines.extend(["", title])
            for path, item in selected:
                code = getattr(item, column)
                lines.append(f"  {labels[code]}:   {path}")
    untracked = [path for path, item in items.items() if item.worktree == "?"]
    if untracked:
        lines.extend(["", "Untracked files:"])
        lines.extend(f"  {path}" for path in untracked)
    if not any(item.staged != " " or item.worktree != " " for item in items.values()):
        lines.extend(["", "nothing to commit, working tree clean"])
    return "\n".join(lines)


def format_short_status(items: Dict[str, StatusItem]) -> str:
    return "\n".join(f"?? {path}" if item.worktree == "?" else f"{item.staged}{item.worktree} {path}" for path, item in items.items())
