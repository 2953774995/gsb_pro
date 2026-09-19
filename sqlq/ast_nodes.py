"""AST node definitions for sqlq statements and expressions."""


class Node:
    __slots__ = ("line", "pos_col")


# --- Expressions -----------------------------------------------------------

class Literal(Node):
    __slots__ = ("value")

    def __init__(self, value, line, column):
        self.value = value
        self.line = line
        self.pos_col = column


class ColumnRef(Node):
    """A bare column or a qualified ``table.column`` reference."""

    __slots__ = ("table", "column")

    def __init__(self, name, line, column, table=None):
        self.table = table
        self.column = name
        self.line = line
        self.pos_col = column


class UnaryOp(Node):
    __slots__ = ("op", "operand")

    def __init__(self, op, operand, line, column):
        # op is one of: -, +, NOT
        self.op = op
        self.operand = operand
        self.line = line
        self.pos_col = column


class BinaryOp(Node):
    __slots__ = ("op", "left", "right")

    def __init__(self, op, left, right, line, column):
        # Arithmetic: + - * / %  Comparisons: = != < <= > >=
        self.op = op
        self.left = left
        self.right = right
        self.line = line
        self.pos_col = column


class IsNull(Node):
    __slots__ = ("operand", "negated")

    def __init__(self, operand, negated, line, column):
        self.operand = operand
        self.negated = negated  # True == IS NOT NULL
        self.line = line
        self.pos_col = column


class FuncCall(Node):
    __slots__ = ("name", "arg", "distinct", "star")

    def __init__(self, name, line, column, arg=None, distinct=False, star=False):
        self.name = name          # always upper case, e.g. COUNT
        self.arg = arg            # None unless star is True (COUNT(*))
        self.distinct = distinct
        self.star = star
        self.line = line
        self.pos_col = column


# --- SELECT projection items ----------------------------------------------

class Star(Node):
    """Unqualified ``*`` in the SELECT list."""

    __slots__ = ()

    def __init__(self, line, column):
        self.line = line
        self.pos_col = column


class QualifiedStar(Node):
    """``table.*`` in the SELECT list."""

    __slots__ = ("table")

    def __init__(self, table, line, column):
        self.table = table
        self.line = line
        self.pos_col = column


class SelectItem(Node):
    __slots__ = ("expr", "alias")

    def __init__(self, expr, alias, line, column):
        self.expr = expr
        self.alias = alias  # str or None
        self.line = line
        self.pos_col = column


class OrderKey(Node):
    __slots__ = ("expr", "descending")

    def __init__(self, expr, descending, line, column):
        self.expr = expr
        self.descending = descending
        self.line = line
        self.pos_col = column


# --- Statements ------------------------------------------------------------

class ColumnDef(Node):
    __slots__ = ("name", "data_type", "primary_key", "not_null")

    def __init__(self, name, data_type, primary_key, line, column,
                 not_null=False):
        self.name = name
        self.data_type = data_type  # INTEGER / REAL / TEXT
        self.primary_key = primary_key
        self.not_null = not_null
        self.line = line
        self.pos_col = column


class CreateTable(Node):
    __slots__ = ("table", "columns")

    def __init__(self, table, columns, line, column):
        self.table = table
        self.columns = columns
        self.line = line
        self.pos_col = column


class DropTable(Node):
    __slots__ = ("table")

    def __init__(self, table, line, column):
        self.table = table
        self.line = line
        self.pos_col = column


class Insert(Node):
    __slots__ = ("table", "columns", "values")

    def __init__(self, table, columns, values, line, column):
        self.table = table
        self.columns = columns  # list[str] or None
        self.values = values    # list[expression]
        self.line = line
        self.pos_col = column


class Update(Node):
    __slots__ = ("table", "assignments", "where")

    def __init__(self, table, assignments, where, line, column):
        self.table = table
        # assignments: list[tuple[column_name, expression]]
        self.assignments = assignments
        self.where = where
        self.line = line
        self.pos_col = column


class Delete(Node):
    __slots__ = ("table", "where")

    def __init__(self, table, where, line, column):
        self.table = table
        self.where = where
        self.line = line
        self.pos_col = column


class Select(Node):
    __slots__ = (
        "distinct", "items", "table", "where", "group_by", "having",
        "order_by", "limit", "offset", "_grouped", "_aggregates",
    )

    def __init__(
        self, distinct, items, table, where, group_by, having,
        order_by, limit, offset, line, column,
    ):
        self.distinct = distinct
        self.items = items
        self.table = table
        self.where = where
        self.group_by = group_by      # list[expression] or None
        self.having = having
        self.order_by = order_by      # list[OrderKey] or None
        self.limit = limit            # expression or None
        self.offset = offset          # expression or None
        self._grouped = False
        self._aggregates = []
        self.line = line
        self.pos_col = column
