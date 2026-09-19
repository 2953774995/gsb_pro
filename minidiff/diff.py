"""Public diff helpers: line/character edit scripts and similarity."""

from collections import namedtuple

from . import _core


Op = namedtuple("Op", ["kind", "old_no", "new_no", "text"])
"""A single edit operation.

``kind`` is ``"equal"``, ``"insert"`` or ``"delete"``; ``old_no`` /
``new_no`` are 1-based line (or character) numbers and are ``None`` on the
side that does not contain the element.
"""


def to_lines(text):
    """Split *text* into lines keeping their trailing newline characters.

    A list is accepted as-is, with a trailing ``"\\n"`` appended to elements
    that lack one.
    """
    if isinstance(text, list):
        return [line if line.endswith("\n") else line + "\n" for line in text]
    if not isinstance(text, str):
        raise TypeError("expected str or list[str], got %r" % type(text))
    return text.splitlines(keepends=True)


def _script(x, y):
    # Fast path: when the two sides share no line at all the LCS is empty,
    # so the shortest script is simply "delete everything, insert
    # everything" -- no need to build a (potentially huge) DP table.
    if x and y and set(x).isdisjoint(y):
        ops = [("delete", i, None, x[i]) for i in range(len(x))]
        ops += [("insert", None, j, y[j]) for j in range(len(y))]
        return ops
    return _core.align(x, y)


def diff_lines(a, b):
    """Compute the line-level edit script between *a* and *b*.

    *a* and *b* may be strings (split on line boundaries) or lists of
    lines.  Returns a list of :class:`Op` tuples.
    """
    x = to_lines(a)
    y = to_lines(b)
    return [
        Op(kind, i + 1 if i is not None else None,
           j + 1 if j is not None else None, value)
        for kind, i, j, value in _script(x, y)
    ]


def diff_chars(a, b):
    """Compute a character-level edit script between two strings."""
    if not isinstance(a, str) or not isinstance(b, str):
        raise TypeError("diff_chars expects str inputs")
    x, y = list(a), list(b)
    return [
        Op(kind, i + 1 if i is not None else None,
           j + 1 if j is not None else None, value)
        for kind, i, j, value in _script(x, y)
    ]


def similarity(a, b):
    """Return the fraction of unchanged lines between *a* and *b*.

    The score is ``2 * equal / (len(a) + len(b))`` and ranges from ``0.0``
    (nothing in common) to ``1.0`` (identical).  Two empty inputs score
    ``1.0``.
    """
    x = to_lines(a)
    y = to_lines(b)
    total = len(x) + len(y)
    if total == 0:
        return 1.0
    equal = 0
    for kind, _, _, _ in _script(x, y):
        if kind == "equal":
            equal += 1
    return (2.0 * equal) / total
