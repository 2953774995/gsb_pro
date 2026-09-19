"""Unified diff rendering and parsing.

A rendered single-file unified diff looks like::

    --- a/file.txt
    +++ b/file.txt
    @@ -1,4 +1,4 @@
     context
    -old
    +new
     context

Every rendered line ends with ``"\\n"``.  A line whose source line lacks a
trailing newline is followed by ``"\\ No newline at end of file"``.
"""

import re

from .diff import diff_lines
from .exceptions import DiffError


class HunkLine:
    """One line inside a hunk.

    ``kind`` is ``" "`` (context), ``"-"`` (removed) or ``"+"`` (added);
    ``text`` keeps the trailing newline when present; ``no_newline`` marks a
    final line without a trailing newline.
    """

    __slots__ = ("kind", "text", "no_newline")

    def __init__(self, kind, text, no_newline=False):
        self.kind = kind
        self.text = text
        self.no_newline = no_newline

    def __eq__(self, other):
        if not isinstance(other, HunkLine):
            return NotImplemented
        return (self.kind == other.kind and self.text == other.text
                and self.no_newline == other.no_newline)

    def __repr__(self):
        return "HunkLine(%r, %r, no_newline=%r)" % (
            self.kind, self.text, self.no_newline)


class Hunk:
    """A ``@@ ... @@`` block plus its lines."""

    __slots__ = ("old_start", "old_len", "new_start", "new_len", "lines",
                 "heading")

    def __init__(self, old_start, old_len, new_start, new_len, lines,
                 heading=""):
        self.old_start = old_start
        self.old_len = old_len
        self.new_start = new_start
        self.new_len = new_len
        self.lines = list(lines)
        self.heading = heading

    def header(self):
        return "@@ -%s +%s @@%s" % (
            _range(self.old_start, self.old_len),
            _range(self.new_start, self.new_len),
            (" " + self.heading) if self.heading else "",
        )

    def __eq__(self, other):
        if not isinstance(other, Hunk):
            return NotImplemented
        return (self.old_start == other.old_start
                and self.old_len == other.old_len
                and self.new_start == other.new_start
                and self.new_len == other.new_len
                and self.lines == other.lines
                and self.heading == other.heading)

    def __repr__(self):
        return "Hunk(old=%s,%s new=%s,%s, %d lines)" % (
            self.old_start, self.old_len, self.new_start, self.new_len,
            len(self.lines))


class Patch:
    """A parsed (or rendered) unified diff.

    ``files`` is a list of ``(fromfile, tofile, hunks)`` tuples -- minidiff
    only produces one-file patches, but parsing accepts multi-file input.
    """

    __slots__ = ("files",)

    def __init__(self, files=None):
        self.files = list(files or [])

    @property
    def fromfile(self):
        return self.files[0][0] if self.files else None

    @property
    def tofile(self):
        return self.files[0][1] if self.files else None

    @property
    def hunks(self):
        return self.files[0][2] if self.files else []

    def __eq__(self, other):
        if not isinstance(other, Patch):
            return NotImplemented
        return self.files == other.files

    def __repr__(self):
        return "Patch(%d file(s))" % len(self.files)


def _range(start, length):
    if length == 0:
        return "%d,0" % start
    if length == 1:
        return str(start)
    return "%d,%d" % (start, length)


def _is_newline(line):
    return line.endswith("\n")


def _group_changes(ops, context):
    """Group op indices into hunk windows separated by wide equal regions."""
    changed = [idx for idx, op in enumerate(ops) if op.kind != "equal"]
    if not changed:
        return []
    groups = []
    start = max(0, changed[0] - context)
    end = min(len(ops), changed[0] + 1 + context)
    for idx in changed[1:]:
        if idx - context <= end:
            end = min(len(ops), idx + 1 + context)
        else:
            groups.append((start, end))
            start = max(0, idx - context)
            end = min(len(ops), idx + 1 + context)
    groups.append((start, end))
    return groups


def _build_hunk(ops, start, end):
    lines = []
    old_count = 0
    new_count = 0
    for op in ops[start:end]:
        if op.kind == "equal":
            lines.append(HunkLine(" ", op.text))
            old_count += 1
            new_count += 1
        elif op.kind == "delete":
            lines.append(HunkLine("-", op.text))
            old_count += 1
        else:
            lines.append(HunkLine("+", op.text))
            new_count += 1
        hl = lines[-1]
        if not _is_newline(hl.text):
            hl.no_newline = True

    first = ops[start]
    if old_count == 0:
        # Insertion-only hunk: anchor after the preceding old line (which
        # may be line 0 when inserting at the very beginning).
        old_start = first.old_no if first.old_no is not None else (
            ops[start - 1].old_no if start > 0 else 0)
    else:
        # Walk back to the first line counted on the old side.
        idx = start
        while ops[idx].kind == "insert":
            idx += 1
        old_start = ops[idx].old_no
    if new_count == 0:
        new_start = first.new_no if first.new_no is not None else (
            ops[start - 1].new_no if start > 0 else 0)
    else:
        idx = start
        while ops[idx].kind == "delete":
            idx += 1
        new_start = ops[idx].new_no

    return Hunk(old_start, old_count, new_start, new_count, lines)


def make_patch(a, b, context=3):
    """Build a structured :class:`Patch` for *a* -> *b*."""
    if not isinstance(context, int) or context < 0:
        raise ValueError("context must be a non-negative integer")
    ops = diff_lines(a, b)
    hunks = [_build_hunk(ops, start, end)
             for start, end in _group_changes(ops, context)]
    return Patch([("a", "b", hunks)])


def render_patch(patch):
    """Serialize a :class:`Patch` into unified-diff text."""
    out = []
    for fromfile, tofile, hunks in patch.files:
        if not hunks:
            continue
        if fromfile is not None:
            out.append("--- %s\n" % fromfile)
        if tofile is not None:
            out.append("+++ %s\n" % tofile)
        for hunk in hunks:
            out.append(hunk.header() + "\n")
            for hl in hunk.lines:
                out.append(hl.kind + hl.text)
                if not hl.text.endswith("\n"):
                    out.append("\n")
                    out.append("\\ No newline at end of file\n")
    return "".join(out)


def unified_diff(a, b, fromfile="a", tofile="b", context=3):
    """Return the unified diff (str) transforming *a* into *b*."""
    patch = make_patch(a, b, context=context)
    if patch.files:
        name, _, hunks = patch.files[0]
        patch.files = [(fromfile, tofile, hunks)]
    return render_patch(patch)


_HUNK_RE = re.compile(
    r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$")


def _strip_name(raw):
    name = raw
    if name.startswith("\"") and name.endswith("\""):
        name = name[1:-1]
    if name.startswith("a/") or name.startswith("b/"):
        name = name[2:]
    return name


def parse_unified_diff(text):
    """Parse unified-diff *text* into a structured :class:`Patch`.

    Raises :class:`~minidiff.exceptions.DiffError` on malformed input.
    """
    if not isinstance(text, str):
        raise DiffError("patch must be a string")
    lines = text.splitlines(keepends=True)
    patch = Patch()
    idx = 0
    total = len(lines)
    saw_diff = False
    pending_from = None
    pending_to = None

    def consume_hunk(match):
        nonlocal idx, saw_diff
        old_start = int(match.group(1))
        old_len = int(match.group(2)) if match.group(2) is not None else 1
        new_start = int(match.group(3))
        new_len = int(match.group(4)) if match.group(4) is not None else 1
        heading = match.group(5).lstrip()
        hunk_lines = []
        idx += 1
        seen_old = seen_new = 0
        while idx < total and (
                seen_old < old_len or seen_new < new_len):
            raw = lines[idx]
            if raw.startswith("@@") or raw.startswith("--- ") \
                    or raw.startswith("+++ ") or raw.startswith("diff "):
                break
            body = raw[1:] if raw[:1] in (" ", "-", "+", "\\") else raw
            no_newline = False
            if body.endswith("\n"):
                body = body[:-1]
                if idx + 1 < total and lines[idx + 1].rstrip("\n") == \
                        "\\ No newline at end of file":
                    no_newline = True
                    idx += 1
            else:
                no_newline = True
            kind = raw[:1]
            if kind == "\\":
                # A stray marker without a preceding diff line is invalid.
                if not hunk_lines:
                    raise DiffError(
                        "unexpected '\\ No newline at end of file' marker")
                hunk_lines[-1].no_newline = True
                idx += 1
                continue
            if kind not in (" ", "-", "+"):
                raise DiffError(
                    "malformed patch line %d: %r" % (idx + 1, raw))
            hl = HunkLine(kind, body + ("" if no_newline else "\n"),
                          no_newline=no_newline)
            if kind == " ":
                seen_old += 1
                seen_new += 1
            elif kind == "-":
                seen_old += 1
            else:
                seen_new += 1
            hunk_lines.append(hl)
            idx += 1
        if seen_old != old_len or seen_new != new_len:
            raise DiffError(
                "hunk @@ -%d,%d +%d,%d @@ line count mismatch "
                "(got %d old / %d new)"
                % (old_start, old_len, new_start, new_len,
                   seen_old, seen_new))
        saw_diff = True
        return Hunk(old_start, old_len, new_start, new_len, hunk_lines,
                    heading)

    current_hunks = []

    def flush():
        nonlocal current_hunks, pending_from, pending_to
        if current_hunks:
            patch.files.append(
                (pending_from if pending_from is not None else "a",
                 pending_to if pending_to is not None else "b",
                 current_hunks))
            current_hunks = []

    while idx < total:
        raw = lines[idx]
        stripped = raw.rstrip("\n")
        if raw.startswith("@@"):
            match = _HUNK_RE.match(stripped)
            if not match:
                raise DiffError(
                    "malformed hunk header at line %d: %r"
                    % (idx + 1, raw))
            current_hunks.append(consume_hunk(match))
        elif raw.startswith("--- "):
            flush()
            pending_from = _strip_name(stripped[4:].strip())
            idx += 1
        elif raw.startswith("+++ "):
            pending_to = _strip_name(stripped[4:].strip())
            idx += 1
        elif raw.startswith("diff ") or raw.startswith("Index: "):
            flush()
            pending_from = pending_to = None
            idx += 1
        elif stripped == "":
            idx += 1
        elif raw.startswith("\\"):
            raise DiffError(
                "unexpected no-newline marker at line %d" % (idx + 1))
        else:
            raise DiffError(
                "unrecognized patch line %d: %r" % (idx + 1, raw))
    flush()

    if not saw_diff:
        raise DiffError("empty or unrecognized patch")
    return patch
