"""Unified diff generation and parsing."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, List, Sequence

from .diff import DELETE, EQUAL, INSERT, DiffOp, diff_lines, split_text_lines
from .patch import DiffError

_NO_NEWLINE = "\\ No newline at end of file"
_HUNK_HEADER_RE = re.compile(
    r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?:[ \t].*)?$"
)
# GNU diff commonly appends a tab and timestamp; minidiff ignores it.
_HEADER_RE = re.compile(r"^(?P<prefix>---|\+\+\+) (?P<path>.*?)(?:\t.*)?$")


@dataclass(frozen=True)
class HunkLine:
    """One line inside a hunk.

    ``kind`` is ``equal``, ``insert`` or ``delete``.  ``text`` excludes the
    unified prefix and the transport newline; ``has_newline`` says whether the
    represented source line has a trailing LF.
    """

    kind: str
    text: str
    has_newline: bool = True


@dataclass(frozen=True)
class Hunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: Sequence[HunkLine] = field(default_factory=tuple)


@dataclass(frozen=True)
class Patch:
    old_path: str
    new_path: str
    hunks: Sequence[Hunk] = field(default_factory=tuple)


def unified_diff(
    a: str | Iterable[str],
    b: str | Iterable[str],
    context: int = 3,
    fromfile: str = "a",
    tofile: str = "b",
) -> str:
    """Return a standard unified diff transforming line list ``a`` to ``b``."""

    if context < 0:
        raise ValueError("context must be non-negative")
    ops = diff_lines(a, b)
    hunks = _build_hunks(ops, context)
    if not hunks:
        return ""
    return render_patch(Patch(fromfile, tofile, hunks))


def render_patch(patch: Patch) -> str:
    """Serialize a :class:`Patch` to unified-diff text."""

    if not patch.hunks:
        return ""

    out: List[str] = [f"--- {patch.old_path}\n", f"+++ {patch.new_path}\n"]
    for hunk in patch.hunks:
        out.append(f"@@ -{_range(hunk.old_start, hunk.old_count)} ")
        out.append(f"+{_range(hunk.new_start, hunk.new_count)} @@\n")
        for line in hunk.lines:
            prefix = {EQUAL: " ", INSERT: "+", DELETE: "-"}[line.kind]
            out.append(prefix + line.text)
            if line.has_newline:
                out.append("\n")
            else:
                out.append("\n" + _NO_NEWLINE + "\n")
    return "".join(out)


def parse_unified_diff(text: str) -> Patch:
    """Parse a single-file unified diff into a structured :class:`Patch`."""

    if not isinstance(text, str):
        raise TypeError("patch text must be a string")

    old_path: str | None = None
    new_path: str | None = None
    hunks: List[Hunk] = []
    current_lines: List[HunkLine] | None = None
    current_header: tuple[int, int, int, int] | None = None
    expect_new_header = False

    def finish_hunk() -> None:
        nonlocal current_lines, current_header
        assert current_header is not None
        assert current_lines is not None
        old_start, old_count, new_start, new_count = current_header
        actual_old = sum(line.kind != INSERT for line in current_lines)
        actual_new = sum(line.kind != DELETE for line in current_lines)
        if actual_old != old_count or actual_new != new_count:
            raise DiffError(
                f"malformed hunk at -{old_start},+{new_start}: "
                f"declared {old_count}/{new_count} lines but found "
                f"{actual_old}/{actual_new}"
            )
        hunks.append(
            Hunk(
                old_start,
                old_count,
                new_start,
                new_count,
                tuple(current_lines),
            )
        )
        current_lines = None
        current_header = None

    def start_hunk(header_line: str) -> None:
        nonlocal current_header, current_lines
        match = _HUNK_HEADER_RE.match(header_line)
        if match is None:
            raise DiffError(f"invalid hunk header: {header_line!r}")
        old_s, old_c, new_s, new_c = match.groups()
        current_header = (
            int(old_s),
            int(old_c if old_c is not None else "1"),
            int(new_s),
            int(new_c if new_c is not None else "1"),
        )
        current_lines = []

    for raw_line in split_text_lines(text):
        # The diff transport itself is LF-delimited.  A CR immediately before
        # that LF belongs to the represented line (CRLF source content).
        transport_newline = raw_line.endswith("\n")
        line = raw_line[:-1] if transport_newline else raw_line

        if expect_new_header:
            if line.startswith("+++ "):
                new_path = _header_path(line)
                expect_new_header = False
                continue
            raise DiffError("expected '+++ ' header after '--- ' header")

        if current_lines is None:
            if line.startswith("--- "):
                if hunks:
                    raise DiffError("multi-file patches are not supported")
                old_path = _header_path(line)
                expect_new_header = True
                continue
            if line.startswith("+++ "):
                if old_path is None or hunks:
                    raise DiffError("unexpected '+++' header")
                new_path = _header_path(line)
                continue
            if line.startswith("@@"):
                start_hunk(line)
                continue
            # Blank separator lines do not contain patch data.  Also tolerate
            # the common git wrapper line; index hashes are not needed.
            if (
                line == ""
                or line.startswith("diff --git ")
                or line.startswith("index ")
            ):
                continue
            raise DiffError(f"unexpected patch line: {raw_line!r}")

        # Inside a hunk.  A new hunk header terminates the previous hunk
        # (this is common for zero-context output).
        if line.startswith("@@"):
            finish_hunk()
            start_hunk(line)
            continue

        if line == _NO_NEWLINE:
            if not current_lines:
                raise DiffError("no-newline marker without a preceding line")
            previous = current_lines[-1]
            current_lines[-1] = HunkLine(
                previous.kind, previous.text, has_newline=False
            )
            continue

        if not line or line[0] not in " +-":
            raise DiffError(f"invalid hunk content: {raw_line!r}")
        prefix = line[0]
        kind = {" ": EQUAL, "+": INSERT, "-": DELETE}[prefix]
        current_lines.append(HunkLine(kind, line[1:], has_newline=True))

    if expect_new_header:
        raise DiffError("patch ends while expecting '+++ ' header")
    if current_lines is not None:
        finish_hunk()

    if not hunks:
        # A completely empty patch is valid; headers by themselves describe an
        # empty patch but carry no path-based changes to apply.
        return Patch(old_path or "a", new_path or "b", ())

    if old_path is None or new_path is None:
        raise DiffError("unified hunks require both '---' and '+++' headers")
    return Patch(old_path, new_path, tuple(hunks))


def _header_path(line: str) -> str:
    match = _HEADER_RE.match(line)
    if match is None:  # pragma: no cover - guarded by the caller
        raise DiffError(f"invalid file header: {line!r}")
    return match.group("path")


def _range(start: int, count: int) -> str:
    if count == 1:
        return str(start)
    return f"{start},{count}"


def _build_hunks(ops: Sequence[DiffOp], context: int) -> List[Hunk]:
    changed_indexes = [i for i, op in enumerate(ops) if op.kind != EQUAL]
    if not changed_indexes:
        return []

    groups: List[tuple[int, int]] = []
    group_start = max(0, changed_indexes[0] - context)
    group_end = min(len(ops), changed_indexes[0] + context + 1)

    for index in changed_indexes[1:]:
        candidate_start = max(0, index - context)
        candidate_end = min(len(ops), index + context + 1)
        if candidate_start <= group_end:
            group_end = max(group_end, candidate_end)
        else:
            groups.append((group_start, group_end))
            group_start, group_end = candidate_start, candidate_end
    groups.append((group_start, group_end))

    return [_make_hunk(ops, start, end) for start, end in groups]


def _make_hunk(ops: Sequence[DiffOp], start: int, end: int) -> Hunk:
    old_before = sum(op.kind != INSERT for op in ops[:start])
    new_before = sum(op.kind != DELETE for op in ops[:start])
    selected = ops[start:end]
    old_count = sum(op.kind != INSERT for op in selected)
    new_count = sum(op.kind != DELETE for op in selected)

    first_old = next((op.old_start for op in selected if op.kind != INSERT), None)
    first_new = next((op.new_start for op in selected if op.kind != DELETE), None)
    old_start = first_old if old_count else old_before
    new_start = first_new if new_count else new_before

    lines: List[HunkLine] = []
    for op in selected:
        physical_line = str(op.value)
        if physical_line.endswith("\n"):
            text = physical_line[:-1]
            has_newline = True
        else:
            text = physical_line
            has_newline = False
        lines.append(HunkLine(op.kind, text, has_newline))

    return Hunk(old_start, old_count, new_start, new_count, tuple(lines))
