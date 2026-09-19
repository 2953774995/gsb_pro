"""Simplified unified diff generation.

The line-level algorithm is classic LCS (O(n*m) dynamic programming),
which is correct for all content including swapped lines.  Output mimics
``diff -u``: file headers, ``@@`` hunk location headers, ``+/-`` line
markers and three lines of context.  ``--stat`` summarises added /
removed line counts per file.
"""


def opcodes(a, b):
    """Return edit script ``[(op, a_i, a_j, b_i, b_j), ...]``.

    ``op`` is one of ``equal`` / ``delete`` / ``insert`` / ``replace``.
    """
    n, m = len(a), len(b)
    # LCS length table, built bottom-up.
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        row = dp[i]
        next_row = dp[i + 1]
        ai = a[i]
        for j in range(m - 1, -1, -1):
            if ai == b[j]:
                row[j] = next_row[j + 1] + 1
            else:
                row[j] = max(next_row[j], row[j + 1])

    ops = []
    i = j = 0

    def flush(start, ai_end, bj_end):
        if start is None:
            return
        ai0, bj0 = start
        if ai0 < ai_end and bj0 < bj_end:
            ops.append(("replace", ai0, ai_end, bj0, bj_end))
        elif ai0 < ai_end:
            ops.append(("delete", ai0, ai_end, bj0, bj0))
        elif bj0 < bj_end:
            ops.append(("insert", ai0, ai0, bj0, bj_end))

    change_start = None  # (i, j) positions immediately before a change
    while i < n or j < m:
        if i < n and j < m and a[i] == b[j]:
            flush(change_start, i, j)
            change_start = None
            ops.append(("equal", i, i + 1, j, j + 1))
            i += 1
            j += 1
        else:
            if change_start is None:
                change_start = (i, j)
            if j >= m or (i < n and dp[i + 1][j] >= dp[i][j + 1]):
                i += 1
            else:
                j += 1
    flush(change_start, i, j)
    return ops


# --------------------------------------------------------------- line splitting
def split_lines(data):
    """Decode bytes to lines preserving newline characters."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    return text.splitlines(keepends=True)


def _group_hunks(ops, context=3):
    """Group opcodes into hunks with ``context`` equal lines around them."""
    change_idx = [k for k, op in enumerate(ops) if op[0] != "equal"]
    if not change_idx:
        return []
    groups = []
    start = end = change_idx[0]
    for idx in change_idx[1:]:
        gap = idx - end - 1  # equal opcodes separating the two changes
        if gap <= 2 * context:
            end = idx
        else:
            groups.append((start, end))
            start = end = idx
    groups.append((start, end))

    hunks = []
    for gs, ge in groups:
        first = max(gs - context, 0)
        last = min(ge + context + 1, len(ops))
        hunks.append(ops[first:last])
    return hunks


def _hunk_lines(hunk, a_lines, b_lines):
    """Render one hunk's body and compute its location/count metadata."""
    out = []
    a_start = b_start = None
    a_count = b_count = 0
    for op, ai, aj, bi, bj in hunk:
        if a_start is None:
            a_start, b_start = ai, bi
        if op == "equal":
            out.append((" ", a_lines[ai]))
            a_count += 1
            b_count += 1
        elif op in ("delete", "replace"):
            for k in range(ai, aj):
                out.append(("-", a_lines[k]))
            a_count += aj - ai
        if op in ("insert", "replace"):
            for k in range(bi, bj):
                out.append(("+", b_lines[k]))
            b_count += bj - bi

    # With splitlines(keepends=True) only the final logical line of a file
    # can lack a newline; emit the standard marker in that case.
    body = []
    for marker, text in out:
        body.append(marker + text)
        if not text.endswith("\n"):
            body.append("\\ No newline at end of file")
    return (
        body,
        a_start + 1 if a_start is not None else 0,
        a_count,
        b_start + 1 if b_start is not None else 0,
        b_count,
    )


def _unified_range(start, count):
    if count == 1:
        return str(start)
    if count == 0:
        return "%d,0" % (start - 1)
    return "%d,%d" % (start, count)


def unified_diff(a_data, b_data, a_label="a/file", b_label="b/file", context=3):
    """Return a unified-diff string between two byte blobs (``""`` if equal)."""
    a_lines = split_lines(a_data)
    b_lines = split_lines(b_data)
    ops = opcodes(a_lines, b_lines)
    hunks = _group_hunks(ops, context)
    if not hunks:
        return ""

    lines = ["--- %s" % a_label, "+++ %s" % b_label]
    for hunk in hunks:
        body, a_start, a_count, b_start, b_count = _hunk_lines(
            hunk, a_lines, b_lines
        )
        lines.append(
            "@@ -%s +%s @@"
            % (_unified_range(a_start, a_count), _unified_range(b_start, b_count))
        )
        lines.extend(body)
    return "\n".join(lines) + "\n"


def count_changes(a_data, b_data):
    """Return ``(added, removed)`` line counts between two blobs."""
    a_lines = split_lines(a_data)
    b_lines = split_lines(b_data)
    added = removed = 0
    for op, ai, aj, bi, bj in opcodes(a_lines, b_lines):
        if op in ("delete", "replace"):
            removed += aj - ai
        if op in ("insert", "replace"):
            added += bj - bi
    return added, removed


# ------------------------------------------------------------- multi-file diff
def diff_entries(old_files, new_files, read_old=None, read_new=None,
                 labels=None, stat=False):
    """Diff two named file sets.

    :param old_files/new_files: ``{path: hash-or-None}``
    :param read_old/read_new: callbacks ``(path) -> bytes``
    :param labels: optional ``(old_prefix, new_prefix)`` label overrides
    """
    old_paths = set(old_files)
    new_paths = set(new_files)
    changed = [
        path for path in sorted(old_paths | new_paths)
        if old_files.get(path) != new_files.get(path)
    ]

    def _old(path):
        return read_old(path) if read_old else b""

    def _new(path):
        return read_new(path) if read_new else b""

    if stat:
        rows = []
        for path in changed:
            added, removed = count_changes(_old(path), _new(path))
            if added or removed:
                rows.append((path, added, removed))
        return format_stat(rows)

    parts = []
    for path in changed:
        la = "%s/%s" % (labels[0] if labels else "a", path)
        lb = "%s/%s" % (labels[1] if labels else "b", path)
        block = unified_diff(_old(path), _new(path), la, lb)
        if block:
            parts.append("diff --git %s %s" % (la, lb))
            parts.append(block.rstrip("\n"))
    return ("\n".join(parts) + "\n") if parts else ""


def format_stat(rows):
    """Render ``--stat`` output: ``name | N +-`` lines plus a summary."""
    if not rows:
        return ""
    name_width = max(len(name) for name, _, _ in rows)
    total_add = sum(a for _, a, _ in rows)
    total_del = sum(d for _, _, d in rows)
    total_changes = total_add + total_del
    bar_width = min(max(total_changes, 1), 40)
    lines = []
    for name, added, removed in rows:
        changes = added + removed
        width = max(1, round(changes / total_changes * bar_width)) if total_changes else 0
        plus = round(added / total_changes * bar_width) if total_changes else 0
        plus = max(0, min(plus, width))
        bar = "+" * plus + "-" * (width - plus)
        lines.append("%s | %d %s" % (name.ljust(name_width), changes, bar))
    lines.append(
        " %d file(s) changed, %d insertion(s)(+), %d deletion(s)(-)"
        % (len(rows), total_add, total_del)
    )
    return "\n".join(lines) + "\n"
