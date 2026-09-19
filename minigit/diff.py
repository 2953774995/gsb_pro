"""Simplified unified diff generation and diff statistics."""

import difflib


def split_lines(data):
    """Split bytes into text lines; return None for binary content."""
    if b"\0" in data:
        return None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return text.splitlines()


def unified_diff(old_data, new_data, old_label, new_label, context=3):
    """Return a unified diff string for two byte blobs (may be empty)."""
    old_lines = split_lines(old_data)
    new_lines = split_lines(new_data)
    if old_lines is None or new_lines is None:
        if old_data == new_data:
            return ""
        return "Binary files %s and %s differ\n" % (old_label, new_label)
    diff = difflib.unified_diff(
        old_lines, new_lines,
        fromfile=old_label, tofile=new_label,
        n=context, lineterm="",
    )
    out = []
    for line in diff:
        out.append(line + "\n")
        if not line.endswith("\n"):
            # Marker for "\ No newline at end of file" is omitted for brevity.
            pass
    return "".join(out)


def count_changes(old_data, new_data):
    """Return (added, deleted) line counts between two byte blobs."""
    old_lines = split_lines(old_data)
    new_lines = split_lines(new_data)
    if old_lines is None or new_lines is None:
        return (0, 0) if old_data == new_data else (1, 1)
    added = deleted = 0
    matcher = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("replace", "delete"):
            deleted += i2 - i1
        if tag in ("replace", "insert"):
            added += j2 - j1
    return added, deleted
