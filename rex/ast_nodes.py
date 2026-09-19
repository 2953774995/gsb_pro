"""Explicit AST node definitions produced by the parser.

The parser builds these nodes; :mod:`rex.engine` compiles them into a tiny
backtracking virtual machine.  Every node carries a source position (the
offset of its first character in the pattern) used for diagnostics.
"""


class Node(object):
    __slots__ = ("pos",)

    def __init__(self, pos=0):
        self.pos = pos


class Literal(Node):
    """A single literal character."""

    __slots__ = ("char",)

    def __init__(self, char, pos=0):
        super().__init__(pos)
        self.char = char

    def __repr__(self):
        return "Literal({!r})".format(self.char)


class Dot(Node):
    """The '.' wildcard: any character except a newline."""

    __slots__ = ()


class CharClass(Node):
    """A bracket expression such as [a-z0-9] or [^abc].

    items is a list of tuples:
      ("char", c)        a single character
      ("range", lo, hi)  an inclusive character range
      ("set", code)      a builtin set: d, D, w, W, s or S
    """

    __slots__ = ("negated", "items")

    def __init__(self, negated, items, pos=0):
        super().__init__(pos)
        self.negated = negated
        self.items = items

    def __repr__(self):
        return "CharClass(negated={!r}, items={!r})".format(self.negated, self.items)


class Anchor(Node):
    """A zero-width anchor: 'start' for ^ and 'end' for $."""

    __slots__ = ("kind",)

    def __init__(self, kind, pos=0):
        super().__init__(pos)
        self.kind = kind

    def __repr__(self):
        return "Anchor({!r})".format(self.kind)


class Concat(Node):
    """An ordered sequence of nodes that must all match in a row."""

    __slots__ = ("nodes",)

    def __init__(self, nodes, pos=0):
        super().__init__(pos)
        self.nodes = nodes

    def __repr__(self):
        return "Concat({!r})".format(self.nodes)


class Alt(Node):
    """Alternation: branches are tried left to right."""

    __slots__ = ("branches",)

    def __init__(self, branches, pos=0):
        super().__init__(pos)
        self.branches = branches

    def __repr__(self):
        return "Alt({!r})".format(self.branches)


class Repeat(Node):
    """A quantified node. max is None for an unbounded repeat."""

    __slots__ = ("node", "min", "max", "greedy")

    def __init__(self, node, min, max, greedy, pos=0):
        super().__init__(pos)
        self.node = node
        self.min = min
        self.max = max
        self.greedy = greedy

    def __repr__(self):
        return "Repeat({!r}, min={!r}, max={!r}, greedy={!r})".format(
            self.node, self.min, self.max, self.greedy
        )


class Group(Node):
    """A group: capturing (numbered or named) or non-capturing.

    * ``slot`` is the runtime capture-slot index for capturing groups, or -1
      for non-capturing groups.
    * ``index`` is the numeric id (1-based) for unnamed capturing groups,
      otherwise None.  Named groups do not consume a numeric index.
    * ``name`` is set for ``(?P<name>...)`` groups.
    """

    __slots__ = ("node", "slot", "index", "name")

    def __init__(self, node, slot=-1, index=None, name=None, pos=0):
        super().__init__(pos)
        self.node = node
        self.slot = slot
        self.index = index
        self.name = name

    def __repr__(self):
        return "Group({!r}, slot={!r}, index={!r}, name={!r})".format(
            self.node, self.slot, self.index, self.name
        )
