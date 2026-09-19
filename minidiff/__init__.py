"""minidiff: a tiny diff and patch implementation using only the standard library."""

from .diff import DiffOp, char_diff, diff_lines, similarity
from .patch import DiffError, apply_patch, reverse_patch
from .unified import Hunk, HunkLine, Patch, parse_unified_diff, render_patch, unified_diff

__all__ = [
    "DiffOp",
    "Hunk",
    "HunkLine",
    "Patch",
    "DiffError",
    "diff_lines",
    "char_diff",
    "similarity",
    "unified_diff",
    "render_patch",
    "parse_unified_diff",
    "apply_patch",
    "reverse_patch",
]

__version__ = "0.1.0"
