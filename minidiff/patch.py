"""Apply (and reverse) unified diffs."""

from .exceptions import DiffError
from .unified import Hunk, HunkLine, Patch, parse_unified_diff, render_patch


def reverse_patch(patch_text):
    """Return the reversed unified-diff text of *patch_text*."""
    patch = parse_unified_diff(patch_text)
    reversed_files = []
    for fromfile, tofile, hunks in patch.files:
        reversed_files.append((tofile, fromfile,
                               [_reverse_hunk(h) for h in hunks]))
    return render_patch(Patch(reversed_files))


def _reverse_hunk(hunk):
    lines = []
    for hl in hunk.lines:
        if hl.kind == "-":
            lines.append(HunkLine("+", hl.text, hl.no_newline))
        elif hl.kind == "+":
            lines.append(HunkLine("-", hl.text, hl.no_newline))
        else:
            lines.append(HunkLine(hl.kind, hl.text, hl.no_newline))
    return Hunk(hunk.new_start, hunk.new_len,
                hunk.old_start, hunk.old_len, lines, hunk.heading)


def _old_expected(hunk):
    """Context and removed lines that must exist in the target text."""
    return [hl for hl in hunk.lines if hl.kind in (" ", "-")]


def _replacement(hunk):
    """Context and added lines that the hunk writes out."""
    return [hl for hl in hunk.lines if hl.kind in (" ", "+")]


def _matches(lines, pos, expected):
    if pos < 0 or pos + len(expected) > len(lines):
        return False
    for offset, hl in enumerate(expected):
        if lines[pos + offset] != hl.text:
            return False
    return True


def apply_patch(text, patch_text, *, reverse=False, fuzz=False):
    """Apply unified diff *patch_text* to *text* and return the result.

    *reverse* applies the patch backwards (new -> old).  *fuzz* allows
    hunks to apply at a shifted position when line numbers have drifted;
    ``fuzz=True`` searches the whole file, an integer *fuzz* limits the
    search to ``expected_position ± fuzz`` lines.

    Raises :class:`~minidiff.exceptions.DiffError` on empty patches,
    out-of-range positions or context mismatches.
    """
    if not isinstance(text, str):
        raise DiffError("text to patch must be a string")
    if patch_text is None or (isinstance(patch_text, str)
                              and not patch_text.strip()):
        raise DiffError("cannot apply an empty patch")
    patch = parse_unified_diff(patch_text)
    if reverse:
        files = [
            (to, from_, [_reverse_hunk(h) for h in hunks])
            for from_, to, hunks in patch.files
        ]
        patch = Patch(files)
    if len(patch.files) != 1:
        raise DiffError(
            "apply_patch only supports single-file patches, got %d"
            % len(patch.files))
    _, _, hunks = patch.files[0]
    if not hunks:
        raise DiffError("patch contains no hunks")

    lines = text.splitlines(keepends=True)
    output = []
    cursor = 0          # first not-yet-consumed index in `lines`
    orig_next = 1       # 1-based original line currently at `cursor`

    for hunk_index, hunk in enumerate(hunks):
        expected = _old_expected(hunk)
        replacement = _replacement(hunk)
        if hunk.old_len > 0:
            # Copy unchanged gap lines up to the hunk anchor.
            gap = hunk.old_start - orig_next
            if gap < 0:
                raise DiffError(
                    "hunk %d overlaps an earlier hunk"
                    % (hunk_index + 1))
            pos = cursor + gap
            if pos + len(expected) > len(lines):
                raise DiffError(
                    "hunk %d reaches beyond end of file (line %d)"
                    % (hunk_index + 1, hunk.old_start))
            if not _matches(lines, pos, expected):
                if fuzz is False:
                    raise DiffError(
                        "hunk %d failed to apply at line %d: "
                        "context mismatch"
                        % (hunk_index + 1, hunk.old_start))
                pos = _find_position(lines, expected, pos, fuzz,
                                     hunk_index)
                gap = pos - cursor
            output.extend(lines[cursor:pos])
            output.extend(hl.text for hl in replacement)
            cursor = pos + len(expected)
            orig_next = hunk.old_start + hunk.old_len
        else:
            # Pure insertion after original line old_start (0 = top).
            gap = hunk.old_start - (orig_next - 1)
            if gap < 0:
                raise DiffError(
                    "hunk %d overlaps an earlier hunk"
                    % (hunk_index + 1))
            pos = cursor + gap
            if pos > len(lines):
                raise DiffError(
                    "hunk %d insertion point is beyond end of file"
                    % hunk_index + 1)
            output.extend(lines[cursor:pos])
            output.extend(hl.text for hl in replacement)
            cursor = pos
            orig_next = hunk.old_start + 1

    output.extend(lines[cursor:])
    return "".join(output)


def _find_position(lines, expected, wanted_pos, fuzz, hunk_index):
    if not expected:
        # Pure insertion: trust the (possibly shifted) line number,
        # clamped into range.
        if 0 <= wanted_pos <= len(lines):
            return wanted_pos
        raise DiffError(
            "hunk %d insertion point line is out of range"
            % (hunk_index + 1))
    limit = None if fuzz is True else int(fuzz)
    last = len(lines) - len(expected)
    # Search nearest-first, scanning outward from the expected position.
    for delta in range(0, len(lines) + 1):
        if limit is not None and delta > limit:
            break
        candidates = [wanted_pos] if delta == 0 else (
            wanted_pos - delta, wanted_pos + delta)
        for candidate in candidates:
            if 0 <= candidate <= last and \
                    _matches(lines, candidate, expected):
                return candidate
    raise DiffError(
        "hunk %d could not be located (fuzzy search exhausted)"
        % (hunk_index + 1))
