"""minidiff: a tiny diff/patch tool built with the Python standard library only.

Public API
----------
diff_lines(a, b)
    Compute a line-level edit script between two strings/list-of-lines.
diff_chars(a, b)
    Compute a character-level edit script.
unified_diff(a, b, fromfile="a", tofile="b", context=3)
    Render a unified diff as text.
parse_unified_diff(text)
    Parse a unified diff back into a structured :class:`Patch`.
apply_patch(text, patch_text, *, reverse=False, fuzz=False)
    Apply a unified diff to text.
similarity(a, b)
    Ratio of unchanged lines (0.0 -- 1.0).

Operations returned by ``diff_lines`` are ``Op(kind, old_no, new_no, text)``
tuples where ``kind`` is one of ``"equal"``, ``"insert"``, ``"delete"`` and
``old_no`` / ``new_no`` are 1-based line numbers (``None`` for the side that
does not contain the line).  Line texts keep their trailing ``"\\n"`` when the
input lines had one.
"""

from .exceptions import DiffError
from .diff import Op, diff_lines, diff_chars, similarity
from .unified import (
    unified_diff,
    parse_unified_diff,
    Hunk,
    Patch,
    HunkLine,
)
from .patch import apply_patch, reverse_patch

__all__ = [
    "DiffError",
    "Op",
    "diff_lines",
    "diff_chars",
    "similarity",
    "unified_diff",
    "parse_unified_diff",
    "apply_patch",
    "reverse_patch",
    "Hunk",
    "Patch",
    "HunkLine",
]
