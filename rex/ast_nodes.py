"""Explicit AST node definitions produced by the parser."""
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class Literal:
    char: str


@dataclass
class Dot:
    """Matches any single character except a newline."""


@dataclass
class Anchor:
    kind: str  # "start" (^) or "end" ($)


# CharClass items are tuples of one of:
#   ("char", c)          a single character
#   ("range", lo, hi)    an inclusive character range
#   ("class", code)      a shorthand class code: d D w W s S
@dataclass
class CharClass:
    negated: bool
    items: List[tuple]


@dataclass
class Concat:
    children: List[object]


@dataclass
class Alt:
    branches: List[object]


@dataclass
class Group:
    child: object
    number: Optional[int]   # 1-based index for numbered groups, else None
    name: Optional[str]     # name for (?P<name>...), else None
    slot: Optional[int]     # internal capture slot, None for (?:...)


@dataclass
class Repeat:
    child: object
    min: int
    max: Optional[int]      # None means unbounded
    greedy: bool
