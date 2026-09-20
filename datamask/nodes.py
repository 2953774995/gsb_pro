"""Explicit AST node definitions for the pattern language.

The parser produces a tree of these nodes; the compiler walks the tree
to emit VM instructions.  Everything is a plain dataclass so the tree
can be inspected and audited easily.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass
class Literal:
    ch: str


@dataclass
class AnyChar:
    """The '.' wildcard: any character except newline."""


@dataclass
class CharClass:
    # items: tuple of ("range", lo, hi) | ("pred", name) | ("npred", name)
    items: Tuple[tuple, ...]
    negated: bool = False


@dataclass
class Anchor:
    kind: str  # "^" (beginning) or "$" (end)


@dataclass
class Concat:
    items: List[object]


@dataclass
class Alternate:
    branches: List[object]


@dataclass
class Group:
    index: Optional[int]  # capture index, None for non-capturing (?:...)
    name: Optional[str]   # name for (?P<name>...), else None
    child: object


@dataclass
class Repeat:
    child: object
    lo: int
    hi: Optional[int]  # None means unbounded
    greedy: bool = True
