"""Edit-script construction.

The public operations are line oriented.  Internally the same sequence
algorithm works on arbitrary hashable values, which also enables the optional
character-level diff.

The primary algorithm is a direct implementation of Eugene W. Myers'
"An O(ND) Difference Algorithm and Its Variations" (1986).  A depth cap keeps
its stored V-snake snapshots bounded for extremely dissimilar inputs; on those
rare cases a Hirschberg-style linear-memory LCS implementation is used.  The
fallback still computes a genuine shortest edit script; only its memory
strategy is different.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Hashable, Iterable, List, Optional, Sequence, Tuple

# Stable string constants are part of the public API.
EQUAL = "equal"
INSERT = "insert"
DELETE = "delete"

# Myers stores O(D^2) snake snapshots.  When two normal files differ by a few
# lines this is tiny.  The cap gives a predictable ceiling while Hirschberg is
# linear in space for adversarial/unrelated inputs.
_MAX_MYERS_DIAGONAL_DEPTH = 512


@dataclass(frozen=True)
class DiffOp:
    """One edit-script operation.

    Line numbers use the same one-based convention as unified diffs.  ``None``
    means that the operation has no position on that side.  Character-level
    operations use offsets starting at zero.
    """

    kind: str
    value: Any
    old_start: Optional[int]
    old_end: Optional[int]
    new_start: Optional[int]
    new_end: Optional[int]

    @property
    def old_number(self) -> Optional[int]:
        return self.old_start

    @property
    def new_number(self) -> Optional[int]:
        return self.new_start


# A compact internal operation is (kind, value).  The caller adds positions.
_InternalOp = Tuple[str, Hashable]


def _normalize_lines(text_or_lines: str | Iterable[str]) -> List[str]:
    """Return lines while preserving LF/CRLF terminators.

    ``str.splitlines`` is intentionally not used because it treats several
    Unicode control characters as line separators.  Patch files traditionally
    split on ``\\n`` only.
    """

    if isinstance(text_or_lines, str):
        return split_text_lines(text_or_lines)
    values: List[str] = []
    for line in text_or_lines:
        if not isinstance(line, str):
            raise TypeError("line sequences must contain strings")
        values.append(line)
    return values


def split_text_lines(text: str) -> List[str]:
    """Split text into physical lines, retaining each trailing line break."""

    if text == "":
        return []
    pieces = text.split("\n")
    lines: List[str] = []
    for index, piece in enumerate(pieces):
        if index < len(pieces) - 1:
            lines.append(piece + "\n")
        elif piece != "":
            # A final piece is omitted when the text ends with a newline; a
            # non-empty last piece is a line without a newline.
            lines.append(piece)
    return lines



def diff_lines(
    a: str | Iterable[str], b: str | Iterable[str]
) -> List[DiffOp]:
    """Compute a shortest line edit script from ``a`` to ``b``.

    Each returned operation has one-based line ranges.  Trailing line breaks
    are preserved as part of the line value, including the special case of a
    final line lacking a newline.
    """

    old = _normalize_lines(a)
    new = _normalize_lines(b)
    return _with_line_numbers(_diff_sequence(old, new))


def char_diff(a: str, b: str) -> List[DiffOp]:
    """Compute a shortest character edit script with zero-based offsets."""

    if not isinstance(a, str) or not isinstance(b, str):
        raise TypeError("char_diff requires strings")
    return _with_char_offsets(_diff_sequence(tuple(a), tuple(b)))


def similarity(a: str | Iterable[str], b: str | Iterable[str]) -> float:
    """Return matched-content density between two line lists.

    The result is ``LCS line count / max(number of old lines, number of new
    lines)``.  It is 1.0 for two empty inputs and 0.0 when one side is empty
    and the other is non-empty.  Only line content participates, matching the
    semantics of the line edit script.
    """

    old = _normalize_lines(a)
    new = _normalize_lines(b)
    denominator = max(len(old), len(new))
    if denominator == 0:
        return 1.0
    return _lcs_length(old, new) / denominator


def _with_line_numbers(ops: Sequence[_InternalOp]) -> List[DiffOp]:
    result: List[DiffOp] = []
    old_no = 1
    new_no = 1
    for kind, value in ops:
        if kind == EQUAL:
            result.append(DiffOp(kind, value, old_no, old_no, new_no, new_no))
            old_no += 1
            new_no += 1
        elif kind == DELETE:
            result.append(DiffOp(kind, value, old_no, old_no, None, None))
            old_no += 1
        elif kind == INSERT:
            result.append(DiffOp(kind, value, None, None, new_no, new_no))
            new_no += 1
        else:  # pragma: no cover - defensive
            raise AssertionError(f"unknown operation {kind!r}")
    return result


def _with_char_offsets(ops: Sequence[_InternalOp]) -> List[DiffOp]:
    result: List[DiffOp] = []
    old_pos = 0
    new_pos = 0
    for kind, value in ops:
        if kind == EQUAL:
            result.append(
                DiffOp(kind, value, old_pos, old_pos + 1, new_pos, new_pos + 1)
            )
            old_pos += 1
            new_pos += 1
        elif kind == DELETE:
            result.append(DiffOp(kind, value, old_pos, old_pos + 1, None, None))
            old_pos += 1
        elif kind == INSERT:
            result.append(DiffOp(kind, value, None, None, new_pos, new_pos + 1))
            new_pos += 1
        else:  # pragma: no cover
            raise AssertionError(f"unknown operation {kind!r}")
    return result


def _diff_sequence(a: Sequence[Hashable], b: Sequence[Hashable]) -> List[_InternalOp]:
    """Return a shortest edit script for arbitrary hashable sequences."""

    if not a and not b:
        return []

    # Common prefixes and suffixes make both algorithms close to linear on
    # typical files with isolated edits.
    prefix = 0
    limit = min(len(a), len(b))
    while prefix < limit and a[prefix] == b[prefix]:
        prefix += 1

    suffix = 0
    while (
        suffix < limit - prefix
        and a[len(a) - 1 - suffix] == b[len(b) - 1 - suffix]
    ):
        suffix += 1

    middle_a = a[prefix : len(a) - suffix]
    middle_b = b[prefix : len(b) - suffix]

    middle = _myers_limited(middle_a, middle_b)
    if middle is None:
        middle = _hirschberg(middle_a, middle_b)

    result: List[_InternalOp] = [(EQUAL, value) for value in a[:prefix]]
    result.extend(middle)
    result.extend((EQUAL, value) for value in a[len(a) - suffix :])
    return result


def _myers_limited(
    a: Sequence[Hashable], b: Sequence[Hashable]
) -> Optional[List[_InternalOp]]:
    """Myers shortest-edit-script with a bounded number of V snapshots."""

    n = len(a)
    m = len(b)
    # Diagonal index d ranges from -d to d; a dict is easiest and robust.
    v: dict[int, int] = {1: 0}
    trace: List[dict[int, int]] = []

    for d in range(0, n + m + 1):
        if d > _MAX_MYERS_DIAGONAL_DEPTH:
            return None
        trace.append(v.copy())
        for k in range(-d, d + 1, 2):
            if k == -d or (k != d and v.get(k - 1, -1) < v.get(k + 1, -1)):
                x = v.get(k + 1, 0)
            else:
                x = v.get(k - 1, -1) + 1
            y = x - k

            while x < n and y < m and a[x] == b[y]:
                x += 1
                y += 1

            v[k] = x
            if x >= n and y >= m:
                return _backtrack_myers(a, b, trace)
    raise AssertionError("unreachable Myers search state")  # pragma: no cover


def _backtrack_myers(
    a: Sequence[Hashable], b: Sequence[Hashable], trace: Sequence[dict[int, int]]
) -> List[_InternalOp]:
    x = len(a)
    y = len(b)
    ops: List[_InternalOp] = []

    for d in range(len(trace) - 1, 0, -1):
        v = trace[d]
        k = x - y
        if k == -d or (k != d and v.get(k - 1, -1) < v.get(k + 1, -1)):
            previous_k = k + 1
            kind = INSERT
        else:
            previous_k = k - 1
            kind = DELETE

        previous_x = v[previous_k]
        previous_y = previous_x - previous_k

        while x > previous_x and y > previous_y:
            ops.append((EQUAL, a[x - 1]))
            x -= 1
            y -= 1

        if kind == DELETE:
            ops.append((DELETE, a[x - 1]))
            x -= 1
        else:
            ops.append((INSERT, b[y - 1]))
            y -= 1

    # d == 0: any remaining overlap consists of a common diagonal/snake.
    while x > 0 and y > 0:
        ops.append((EQUAL, a[x - 1]))
        x -= 1
        y -= 1

    ops.reverse()
    return ops


def _hirschberg(
    a: Sequence[Hashable], b: Sequence[Hashable]
) -> List[_InternalOp]:
    """Linear-memory LCS-based shortest edit script.

    Classic Hirschberg normally returns just the LCS.  The recursive calls here
    emit deletions/insertions as well; those are required to build a full SES.
    """

    ops: List[_InternalOp] = []

    def recurse(x: Sequence[Hashable], y: Sequence[Hashable]) -> None:
        if len(y) == 0:
            for value in x:
                ops.append((DELETE, value))
            return
        if len(x) == 0:
            for value in y:
                ops.append((INSERT, value))
            return
        if len(x) == 1:
            try:
                index = y.index(x[0])
            except ValueError:
                ops.append((DELETE, x[0]))
                for value in y:
                    ops.append((INSERT, value))
            else:
                for value in y[:index]:
                    ops.append((INSERT, value))
                ops.append((EQUAL, x[0]))
                for value in y[index + 1 :]:
                    ops.append((INSERT, value))
            return

        if len(x) >= len(y):
            x_mid = len(x) // 2
            score_l = _lcs_row(x[:x_mid], y)
            score_r_reversed = _lcs_row(x[x_mid:][::-1], y[::-1])
            score_r = score_r_reversed[::-1]
            y_mid = max(
                range(len(y) + 1),
                key=lambda j: score_l[j] + score_r[j],
            )
        else:
            # Split the longer second sequence instead.  The rolling DP row
            # then remains indexed by the shorter first sequence.
            y_mid = len(y) // 2
            score_l = _lcs_row(y[:y_mid], x)
            score_r_reversed = _lcs_row(y[y_mid:][::-1], x[::-1])
            score_r = score_r_reversed[::-1]
            x_mid = max(
                range(len(x) + 1),
                key=lambda i: score_l[i] + score_r[i],
            )

        recurse(x[:x_mid], y[:y_mid])
        recurse(x[x_mid:], y[y_mid:])

    recurse(a, b)
    return ops


def _lcs_row(a: Sequence[Hashable], b: Sequence[Hashable]) -> List[int]:
    """Final DP row of LCS lengths using two one-dimensional arrays."""

    previous = [0] * (len(b) + 1)
    current = [0] * (len(b) + 1)
    for value_a in a:
        current[0] = 0
        for j, value_b in enumerate(b, start=1):
            if value_a == value_b:
                current[j] = previous[j - 1] + 1
            else:
                current[j] = max(previous[j], current[j - 1])
        previous, current = current, previous
    return previous


def _lcs_length(a: Sequence[Hashable], b: Sequence[Hashable]) -> int:
    # Let b be the shorter dimension for the rolling LCS row.
    if len(a) < len(b):
        a, b = b, a
    return _lcs_row(a, b)[-1]
