"""Simplified unified-diff generation and line statistics (difflib based)."""

import difflib

CONTEXT_LINES = 3


def unified_diff(old_text, new_text, old_label, new_label, context=CONTEXT_LINES):
    """Return a unified diff string with @@ hunk headers and 3 context lines."""
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()
    lines = difflib.unified_diff(
        old_lines, new_lines,
        fromfile=old_label, tofile=new_label,
        n=context, lineterm="",
    )
    return "\n".join(lines)


def count_changes(old_text, new_text):
    """Return ``(added, deleted)`` line counts between two texts."""
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()
    matcher = difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)
    added = deleted = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("replace", "delete"):
            deleted += i2 - i1
        if tag in ("replace", "insert"):
            added += j2 - j1
    return added, deleted
