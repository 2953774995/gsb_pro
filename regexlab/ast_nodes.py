"""AST node definitions for parsed regex patterns.

The parser turns a pattern string into a tree built from these nodes;
the matching engine then walks the tree with a backtracking algorithm.

Plain classes are used (instead of dataclasses) so that importing this
package never pulls in the stdlib ``re`` module, even transitively.
"""


class _Node:
    """Base class providing a generic repr for AST nodes."""

    __slots__ = ()
    _fields = ()

    def __repr__(self):
        args = ", ".join("%s=%r" % (name, getattr(self, name))
                         for name in self._fields)
        return "%s(%s)" % (type(self).__name__, args)

    def __eq__(self, other):
        return (type(self) is type(other) and
                all(getattr(self, f) == getattr(other, f)
                    for f in self._fields))


class Literal(_Node):
    """A single literal character."""
    __slots__ = ("char",)
    _fields = ("char",)

    def __init__(self, char):
        self.char = char


class AnyChar(_Node):
    """The dot ``.`` -- matches any character except a newline."""


class Predefined(_Node):
    """A predefined escape class: one of d, D, w, W, s, S."""
    __slots__ = ("kind",)
    _fields = ("kind",)

    def __init__(self, kind):
        self.kind = kind


class CharClass(_Node):
    """A ``[...]`` character class, possibly negated with ``^``.

    ``items`` is a list of ("range", lo, hi) inclusive code-point ranges
    and ("pre", kind) predefined classes.
    """
    __slots__ = ("items", "negated")
    _fields = ("items", "negated")

    def __init__(self, items, negated):
        self.items = items
        self.negated = negated


class Sequence(_Node):
    """Concatenation of sub-expressions."""
    __slots__ = ("items",)
    _fields = ("items",)

    def __init__(self, items):
        self.items = items


class Alternation(_Node):
    """An ``a|b|c`` choice between branches, tried left to right."""
    __slots__ = ("branches",)
    _fields = ("branches",)

    def __init__(self, branches):
        self.branches = branches


class Repeat(_Node):
    """A quantified expression. ``max`` of None means unbounded."""
    __slots__ = ("child", "min", "max", "greedy")
    _fields = ("child", "min", "max", "greedy")

    def __init__(self, child, min, max, greedy):
        self.child = child
        self.min = min
        self.max = max
        self.greedy = greedy


class Group(_Node):
    """A group. ``index`` is the 1-based capture number, or None for
    non-capturing groups ``(?:...)``."""
    __slots__ = ("child", "index")
    _fields = ("child", "index")

    def __init__(self, child, index):
        self.child = child
        self.index = index


class Start(_Node):
    """The ``^`` anchor: matches only at the start of the string."""


class End(_Node):
    """The ``$`` anchor: matches only at the end of the string."""


class WordBoundary(_Node):
    """``\\b`` (negated=False) or ``\\B`` (negated=True)."""
    __slots__ = ("negated",)
    _fields = ("negated",)

    def __init__(self, negated):
        self.negated = negated
