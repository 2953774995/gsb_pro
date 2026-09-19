"""AST node definitions produced by the parser and consumed by the executor."""

from dataclasses import dataclass, field
from typing import Any, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Expression nodes
# ---------------------------------------------------------------------------


@dataclass
class Literal:
    value: Any  # int, float, str or None


@dataclass
class Column:
    name: str  # normalised to lower case
    table: Optional[str] = None  # normalised to lower case when provided


@dataclass
class UnaryOp:
    op: str  # '-', '+' or 'NOT'
    operand: Any


@dataclass
class BinaryOp:
    op: str  # arithmetic, comparison or logical operator
    left: Any
    right: Any


@dataclass
class IsNull:
    operand: Any
    negated: bool = False  # True for IS NOT NULL


@dataclass
class Aggregate:
    name: str  # COUNT / SUM / AVG / MIN / MAX (upper case)
    arg: Any = None  # expression node or None for COUNT(*)
    star: bool = False
    distinct: bool = False


@dataclass
class Star:
    """The bare ``*`` projection item."""


# ---------------------------------------------------------------------------
# Statement nodes
# ---------------------------------------------------------------------------


@dataclass
class CreateTable:
    name: str  # original spelling
    columns: List[Tuple[str, str]]  # (column name original spelling, type upper)
    primary_key: Optional[str] = None  # lower-cased column name


@dataclass
class DropTable:
    name: str


@dataclass
class Insert:
    table: str
    columns: Optional[List[str]]  # original spellings, or None for all columns
    values: List[Any]  # list of expression nodes


@dataclass
class Update:
    table: str
    assignments: List[Tuple[str, Any, Any]]  # (column name, expr, qualifier)
    where: Optional[Any] = None


@dataclass
class Delete:
    table: str
    where: Optional[Any] = None


@dataclass
class SelectItem:
    expr: Any
    alias: Optional[str] = None  # original spelling after AS


@dataclass
class OrderTerm:
    expr: Any
    descending: bool = False


@dataclass
class Select:
    items: List[SelectItem]
    table: Optional[str] = None  # SELECT without FROM is allowed for constants
    where: Optional[Any] = None
    group_by: List[Any] = field(default_factory=list)
    having: Optional[Any] = None
    order_by: List[OrderTerm] = field(default_factory=list)
    distinct: bool = False
    limit: Optional[int] = None
    offset: int = 0
