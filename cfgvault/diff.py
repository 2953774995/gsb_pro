"""Simplified line-level unified diff and statistics."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .trees import IndexEntry


@dataclass(frozen=True)
class FileStat:
    path: str
    insertions: int
    deletions: int
    status: str
    binary: bool = False


def _split_lines(data: bytes) -> tuple[list[str], bool]:
    if not data:
        return [], True
    text = data.decode("utf-8")
    lines = text.splitlines(keepends=True)
    return lines, text.endswith("\n")


def _is_binary(data: bytes) -> bool:
    if b"\x00" in data:
        return True
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return True
    return False


def _format_range(start: int, count: int) -> str:
    # Unified diff ranges are one-based.  An empty file is conventionally 0,0.
    if count == 0:
        pos = 0 if start == 0 else start + 1
        return f"{pos},0"
    if count == 1:
        return str(start + 1)
    return f"{start + 1},{count}"


def _hunks(old: Sequence[str], new: Sequence[str], context: int = 3) -> list[str]:
    matcher = SequenceMatcher(a=old, b=new, autojunk=False)
    opcodes = matcher.get_opcodes()
    change_ranges: list[tuple[int, int, int, int]] = []
    for tag, i1, i2, j1, j2 in opcodes:
        if tag != "equal":
            change_ranges.append((i1, i2, j1, j2))
    if not change_ranges:
        return []

    groups: list[list[tuple[int, int, int, int]]] = []
    for change in change_ranges:
        if not groups:
            groups.append([change])
            continue
        prev_i2 = groups[-1][-1][1]
        if change[0] - prev_i2 <= 2 * context:
            groups[-1].append(change)
        else:
            groups.append([change])

    output: list[str] = []
    for group in groups:
        first = group[0]
        last = group[-1]
        old_start = max(0, first[0] - context)
        new_start = max(0, first[2] - context)
        old_end = min(len(old), last[1] + context)
        new_end = min(len(new), last[3] + context)
        output.append(
            "@@ -"
            + _format_range(old_start, old_end - old_start)
            + " +"
            + _format_range(new_start, new_end - new_start)
            + " @@"
        )
        # Regenerate tags across the complete window so contextual lines are
        # emitted between nearby changes.  Pure insertions have an empty old
        # range, so they must be selected using their new range.
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            old_lo = max(i1, old_start)
            old_hi = min(i2, old_end)
            new_lo = max(j1, new_start)
            new_hi = min(j2, new_end)
            if tag == "equal":
                if old_lo < old_hi:
                    for line in old[old_lo:old_hi]:
                        output.append(" " + line)
            else:
                if old_lo < old_hi:
                    for line in old[old_lo:old_hi]:
                        output.append("-" + line)
                if new_lo < new_hi:
                    for line in new[new_lo:new_hi]:
                        output.append("+" + line)
    return [line if line.endswith("\n") else line + "\n" for line in output]


def diff_file(path: str, old_data: Optional[bytes], new_data: Optional[bytes]) -> tuple[list[str], FileStat]:
    old_data = old_data or b""
    new_data = new_data or b""
    if old_data == new_data:
        return [], FileStat(path, 0, 0, "unchanged")
    if _is_binary(old_data) or _is_binary(new_data):
        status = "added" if not old_data else "deleted" if not new_data else "modified"
        return [f"Binary files differ: {path}\n"], FileStat(path, 0, 0, status, binary=True)

    old_lines, _ = _split_lines(old_data)
    new_lines, _ = _split_lines(new_data)
    status = "added" if not old_data else "deleted" if not new_data else "modified"
    matcher = SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)
    insertions = sum(j2 - j1 for tag, _i1, _i2, j1, j2 in matcher.get_opcodes() if tag != "equal")
    deletions = sum(i2 - i1 for tag, i1, i2, _j1, _j2 in matcher.get_opcodes() if tag != "equal")
    # For pure additions/deletions opcodes already have one side at zero.
    body = _hunks(old_lines, new_lines)
    header = [f"--- a/{path}\n", f"+++ b/{path}\n"]
    return header + body, FileStat(path, insertions, deletions, status)


def compare_entries(
    old_entries: Dict[str, IndexEntry],
    new_entries: Dict[str, IndexEntry],
    blob_loader,
) -> tuple[str, list[FileStat]]:
    paths = sorted(set(old_entries) | set(new_entries))
    chunks: list[str] = []
    stats: list[FileStat] = []
    for path in paths:
        old_oid = old_entries.get(path).oid if path in old_entries else None
        new_oid = new_entries.get(path).oid if path in new_entries else None
        if old_oid == new_oid:
            continue
        old_data = blob_loader(old_oid) if old_oid else None
        new_data = blob_loader(new_oid) if new_oid else None
        chunk, stat = diff_file(path, old_data, new_data)
        if chunk:
            chunks.extend(chunk)
            stats.append(stat)
    return "".join(chunks), stats


def format_stat(stats: Iterable[FileStat]) -> str:
    stats = list(stats)
    if not stats:
        return ""
    names = [item.path for item in stats]
    width = max((len(name) for name in names), default=0)
    lines = []
    files_changed = 0
    insertions = 0
    deletions = 0
    for item in stats:
        if item.binary or item.insertions + item.deletions == 0:
            bar = "Bin"
        else:
            total = min(item.insertions + item.deletions, 60)
            total_changes = item.insertions + item.deletions
            # Scale changes into a compact bar while preserving +/-.
            plus_bar = round(item.insertions / max(1, total_changes) * total)
            minus_bar = total - plus_bar
            bar = "+" * plus_bar + "-" * minus_bar
        count = "" if item.binary else f" {item.insertions}+/{item.deletions}-"
        lines.append(f"{item.path:<{width}} | {bar}{count}")
        files_changed += 1
        insertions += item.insertions
        deletions += item.deletions
    lines.append(
        f" {files_changed} file(s) changed, {insertions} insertion(s)(+), {deletions} deletion(s)(-)"
    )
    return "\n".join(lines) + "\n"
