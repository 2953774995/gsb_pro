"""Apply and reverse structured unified patches."""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Union

from .diff import DELETE, EQUAL, INSERT, split_text_lines

if TYPE_CHECKING:
    from .unified import Patch


class DiffError(Exception):
    """Raised when a patch is invalid or cannot be applied."""


def apply_patch(
    text: str,
    patch: Union["Patch", str],
    *,
    reverse: bool = False,
    fuzz: bool = True,
) -> str:
    """Apply a single-file unified patch to ``text``.

    Parameters
    ----------
    text:
        Original file content.
    patch:
        Either unified diff text or a structured ``Patch``.
    reverse:
        Apply the patch backwards (new content becomes the input).
    fuzz:
        When true, ignore the hunk's line-number offset and search for its
        exact context/removal block nearby. Context itself is still required to
        match exactly.  Pure insertions have no anchor and therefore rely on
        their hunk position even when this option is enabled.
    """

    if not isinstance(text, str):
        raise TypeError("text must be a string")
    if isinstance(patch, str):
        from .unified import parse_unified_diff

        structured = parse_unified_diff(patch)
    else:
        structured = patch

    # The duck-typed check avoids a circular module import at module load.
    if not hasattr(structured, "hunks"):
        raise TypeError("patch must be unified diff text or a Patch object")
    if reverse:
        structured = reverse_patch(structured)
    if not structured.hunks:
        raise DiffError("cannot apply an empty patch")

    current: List[str] = split_text_lines(text)
    cumulative_delta = 0
    cursor = 0

    for hunk_index, hunk in enumerate(structured.hunks, start=1):
        old_pattern = [
            _physical(line) for line in hunk.lines if line.kind != INSERT
        ]
        new_pattern = [
            _physical(line) for line in hunk.lines if line.kind != DELETE
        ]

        # Coordinates refer to the side being patched.  A zero-length old side
        # marks an insertion between lines; its start is the line before it
        # (0 at the top, n at EOF).
        original_side_length = len(current) - cumulative_delta
        if hunk.old_count == 0:
            in_bounds = 0 <= hunk.old_start <= original_side_length
        else:
            in_bounds = 1 <= hunk.old_start <= original_side_length
        if not in_bounds:
            raise DiffError(
                f"hunk {hunk_index}: old start line {hunk.old_start} is out "
                f"of bounds for {original_side_length} lines"
            )
        if hunk.old_count != len(old_pattern) or hunk.new_count != len(new_pattern):
            raise DiffError(f"hunk {hunk_index}: hunk counts do not match body")

        preferred = (
            hunk.old_start if hunk.old_count == 0 else hunk.old_start - 1
        ) + cumulative_delta
        end = len(current) - len(old_pattern)
        matches_preferred = (
            current[preferred : preferred + len(old_pattern)] == old_pattern
        )
        if preferred < cursor or preferred > end or not matches_preferred:
            if not fuzz or len(old_pattern) == 0:
                raise DiffError(
                    f"hunk {hunk_index}: context mismatch at line {hunk.old_start}"
                )
            candidates = [
                position
                for position in range(cursor, end + 1)
                if current[position : position + len(old_pattern)] == old_pattern
            ]
            if not candidates:
                raise DiffError(
                    f"hunk {hunk_index}: context mismatch near line {hunk.old_start}"
                )
            position = min(
                candidates, key=lambda candidate: abs(candidate - preferred)
            )
        else:
            position = preferred

        current[position : position + len(old_pattern)] = new_pattern
        cumulative_delta += len(new_pattern) - len(old_pattern)
        cursor = position + len(new_pattern)

    return "".join(current)


def reverse_patch(patch: Patch) -> Patch:
    """Swap old and new sides of every hunk."""

    from .unified import Hunk, HunkLine, Patch

    reversed_hunks = []
    for hunk in patch.hunks:
        flipped_lines = tuple(
            HunkLine(
                {
                    EQUAL: EQUAL,
                    INSERT: DELETE,
                    DELETE: INSERT,
                }[line.kind],
                line.text,
                line.has_newline,
            )
            for line in hunk.lines
        )
        reversed_hunks.append(
            Hunk(
                hunk.new_start,
                hunk.new_count,
                hunk.old_start,
                hunk.old_count,
                flipped_lines,
            )
        )
    return Patch(patch.new_path, patch.old_path, tuple(reversed_hunks))


def _physical(line: "HunkLine") -> str:
    return line.text + ("\n" if line.has_newline else "")
