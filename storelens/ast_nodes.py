"""AST node definitions for the storelens query language."""


# ---------------------------------------------------------------------------
# Expressions
# ---------------------------------------------------------------------------

class Expr:
    __slots__ = ()


class Literal(Expr):
    __slots__ = ("value",)

    def __init__(self, value):
        self.value = value  # int, float, str, or None (NULL)


class Column(Expr):
    __slots__ = ("name",)

    def __init__(self, name):
        self.name = name


class Star(Expr):
    """The * wildcard in a SELECT list or COUNT(*)."""
    __slots__ = ()


class UnaryOp(Expr):
    __slots__ = ("op", "operand")

    def __init__(self, op, operand):
        self.op = op  # '-', '+', 'NOT'
        self.operand = operand


class BinaryOp(Expr):
    __slots__ = ("op", "left", "right")

    def __init__(self, op, left, right):
        self.op = op  # arithmetic, comparison, AND / OR
        self.left = left
        self.right = right


class IsNull(Expr):
    __slots__ = ("operand", "negated")

    def __init__(self, operand, negated=False):
        self.operand = operand
        self.negated = negated


class FuncCall(Expr):
    __slots__ = ("name", "args", "star")

    def __init__(self, name, args, star=False):
        self.name = name.upper()
        self.args = args
        self.star = star  # COUNT(*)


# ---------------------------------------------------------------------------
# Statements
# ---------------------------------------------------------------------------

class ColumnDef:
    __slots__ = ("name", "type_name", "primary_key")

    def __init__(self, name, type_name, primary_key=False):
        self.name = name
        self.type_name = type_name  # INTEGER / REAL / TEXT
        self.primary_key = primary_key


class CreateTable:
    __slots__ = ("name", "columns")

    def __init__(self, name, columns):
        self.name = name
        self.columns = columns  # list of ColumnDef


class DropTable:
    __slots__ = ("name",)

    def __init__(self, name):
        self.name = name


class Insert:
    __slots__ = ("table", "columns", "rows")

    def __init__(self, table, columns, rows):
        self.table = table
        self.columns = columns  # list of column names or None (all columns)
        self.rows = rows        # list of list of Expr


class Update:
    __slots__ = ("table", "assignments", "where")

    def __init__(self, table, assignments, where):
        self.table = table
        self.assignments = assignments  # list of (column_name, Expr)
        self.where = where              # Expr or None


class Delete:
    __slots__ = ("table", "where")

    def __init__(self, table, where):
        self.table = table
        self.where = where


class SelectItem:
    __slots__ = ("expr", "alias")

    def __init__(self, expr, alias=None):
        self.expr = expr
        self.alias = alias


class OrderItem:
    __slots__ = ("expr", "descending")

    def __init__(self, expr, descending=False):
        self.expr = expr
        self.descending = descending


class Select:
    __slots__ = ("distinct", "items", "table", "where", "group_by",
                 "having", "order_by", "limit", "offset")

    def __init__(self, distinct, items, table, where, group_by, having,
                 order_by, limit, offset):
        self.distinct = distinct
        self.items = items          # list of SelectItem
        self.table = table
        self.where = where
        self.group_by = group_by    # list of Expr
        self.having = having
        self.order_by = order_by    # list of OrderItem
        self.limit = limit          # int or None
        self.offset = offset        # int or None
