"""AST node definitions for the storelens query language."""


# ---------- expressions ----------

class Expr:
    __slots__ = ()


class Literal(Expr):
    __slots__ = ("value",)

    def __init__(self, value):
        self.value = value  # int | float | str | None


class Column(Expr):
    __slots__ = ("name",)

    def __init__(self, name):
        self.name = name


class Star(Expr):
    """The '*' in SELECT * or COUNT(*)."""
    __slots__ = ()


class Unary(Expr):
    __slots__ = ("op", "operand")

    def __init__(self, op, operand):
        self.op = op          # 'NOT' | '-'
        self.operand = operand


class Binary(Expr):
    __slots__ = ("op", "left", "right")

    def __init__(self, op, left, right):
        self.op = op          # arithmetic, comparison, AND / OR
        self.left = left
        self.right = right


class IsNull(Expr):
    __slots__ = ("operand", "negated")

    def __init__(self, operand, negated):
        self.operand = operand
        self.negated = negated


class FuncCall(Expr):
    __slots__ = ("name", "arg")

    def __init__(self, name, arg):
        self.name = name      # COUNT | SUM | AVG | MIN | MAX
        self.arg = arg        # Expr or Star


AGGREGATES = ("COUNT", "SUM", "AVG", "MIN", "MAX")


def contains_aggregate(expr):
    if isinstance(expr, FuncCall):
        return True
    if isinstance(expr, Unary):
        return contains_aggregate(expr.operand)
    if isinstance(expr, Binary):
        return contains_aggregate(expr.left) or contains_aggregate(expr.right)
    if isinstance(expr, IsNull):
        return contains_aggregate(expr.operand)
    return False


# ---------- statements ----------

class Statement:
    __slots__ = ()


class CreateTable(Statement):
    __slots__ = ("name", "columns")

    def __init__(self, name, columns):
        self.name = name
        self.columns = columns  # list of (col_name, type_name, is_primary_key)


class DropTable(Statement):
    __slots__ = ("name",)

    def __init__(self, name):
        self.name = name


class Insert(Statement):
    __slots__ = ("table", "columns", "rows")

    def __init__(self, table, columns, rows):
        self.table = table
        self.columns = columns  # list of names or None
        self.rows = rows        # list of list of Expr


class Update(Statement):
    __slots__ = ("table", "assignments", "where")

    def __init__(self, table, assignments, where):
        self.table = table
        self.assignments = assignments  # list of (col_name, Expr)
        self.where = where              # Expr or None


class Delete(Statement):
    __slots__ = ("table", "where")

    def __init__(self, table, where):
        self.table = table
        self.where = where


class SelectItem:
    __slots__ = ("expr", "alias")

    def __init__(self, expr, alias):
        self.expr = expr
        self.alias = alias


class Select(Statement):
    __slots__ = ("distinct", "items", "table", "where", "group_by",
                 "having", "order_by", "limit", "offset")

    def __init__(self, distinct, items, table, where, group_by, having,
                 order_by, limit, offset):
        self.distinct = distinct
        self.items = items              # list of SelectItem
        self.table = table
        self.where = where              # Expr or None
        self.group_by = group_by        # list of Expr
        self.having = having            # Expr or None
        self.order_by = order_by        # list of (Expr, 'ASC'|'DESC')
        self.limit = limit              # int or None
        self.offset = offset            # int or None
