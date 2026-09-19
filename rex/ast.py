"""AST node definitions for the rex regex engine.

The parser produces a tree built from these node types:

* ``Literal(ch)``            -- a single character
* ``Dot()``                  -- ``.`` (any char except ``\\n``)
* ``CharClass(items, neg)``  -- ``[...]``; items are ``("lit", ch)``,
  ``("range", lo, hi)`` or ``("class", name)`` tuples
* ``ClassEscape(name)``      -- ``\\d`` etc. outside of a class
* ``Anchor(kind)``           -- ``^`` (``"start"``) or ``$`` (``"end"``)
* ``Concat(children)``
* ``Alternate(branches)``
* ``Repeat(child, lo, hi, greedy)`` -- ``hi`` is ``None`` for unbounded
* ``Group(child, index, name)``     -- ``index`` is ``None`` for
  non-capturing groups
"""


class Node:
    __slots__ = ()


class Literal(Node):
    __slots__ = ("char",)

    def __init__(self, char):
        self.char = char


class Dot(Node):
    __slots__ = ()


class CharClass(Node):
    __slots__ = ("items", "negated")

    def __init__(self, items, negated):
        self.items = items
        self.negated = negated


class ClassEscape(Node):
    __slots__ = ("name",)

    def __init__(self, name):
        self.name = name


class Anchor(Node):
    __slots__ = ("kind",)

    def __init__(self, kind):
        self.kind = kind  # "start" or "end"


class Concat(Node):
    __slots__ = ("children",)

    def __init__(self, children):
        self.children = children


class Alternate(Node):
    __slots__ = ("branches",)

    def __init__(self, branches):
        self.branches = branches


class Repeat(Node):
    __slots__ = ("child", "min", "max", "greedy")

    def __init__(self, child, min_count, max_count, greedy):
        self.child = child
        self.min = min_count
        self.max = max_count  # None means unbounded
        self.greedy = greedy


class Group(Node):
    __slots__ = ("child", "index", "name")

    def __init__(self, child, index, name=None):
        self.child = child
        self.index = index  # None for non-capturing groups
        self.name = name
