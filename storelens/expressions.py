"""Expression evaluation with SQL-style three-valued logic.

Missing values are represented as None. Any comparison involving a
missing value evaluates to None (unknown), which does not satisfy a
WHERE clause. AND / OR / NOT implement full three-valued logic.
"""

from .errors import StorelensError
from .ast_nodes import Literal, Column, UnaryOp, BinaryOp, IsNull, FuncCall, Star
from .types import is_number


class RowContext:
    """Binds a row of a table (plus optional precomputed aggregates)."""

    def __init__(self, table, row, agg_values=None):
        self.table = table
        self.row = row
        self.agg_values = agg_values or {}


def to_bool(value):
    """Map a value to the three-valued boolean domain True / False / None."""
    if value is None:
        return None
    return bool(value)


def matches(value):
    """A WHERE/HAVING condition matches only when it is True."""
    return to_bool(value) is True


def evaluate(expr, ctx):
    if isinstance(expr, Literal):
        return expr.value
    if isinstance(expr, Column):
        idx = ctx.table.column_index(expr.name)
        if ctx.row is None or idx >= len(ctx.row):
            raise StorelensError(
                "Column '%s' cannot be referenced in this context"
                % expr.name)
        return ctx.row[idx]
    if isinstance(expr, IsNull):
        value = evaluate(expr.operand, ctx)
        result = value is None
        return (not result) if expr.negated else result
    if isinstance(expr, UnaryOp):
        return _eval_unary(expr, ctx)
    if isinstance(expr, BinaryOp):
        return _eval_binary(expr, ctx)
    if isinstance(expr, FuncCall):
        key = id(expr)
        if key in ctx.agg_values:
            return ctx.agg_values[key]
        raise StorelensError(
            "Aggregate function %s cannot be used in this context"
            % expr.name)
    if isinstance(expr, Star):
        raise StorelensError("'*' is only allowed in a SELECT list or "
                             "COUNT(*)")
    raise StorelensError("Unsupported expression: %r" % (expr,))


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

def _eval_unary(expr, ctx):
    if expr.op == "NOT":
        value = to_bool(evaluate(expr.operand, ctx))
        return None if value is None else (not value)
    value = evaluate(expr.operand, ctx)
    if value is None:
        return None
    if not is_number(value):
        raise StorelensError(
            "Unary %s requires a numeric operand, got %r" % (expr.op, value))
    return -value if expr.op == "-" else +value


def _eval_binary(expr, ctx):
    op = expr.op
    if op == "AND":
        left = to_bool(evaluate(expr.left, ctx))
        if left is False:
            return False
        right = to_bool(evaluate(expr.right, ctx))
        if right is False:
            return False
        if left is None or right is None:
            return None
        return True
    if op == "OR":
        left = to_bool(evaluate(expr.left, ctx))
        if left is True:
            return True
        right = to_bool(evaluate(expr.right, ctx))
        if right is True:
            return True
        if left is None or right is None:
            return None
        return False

    left = evaluate(expr.left, ctx)
    right = evaluate(expr.right, ctx)

    if op in ("=", "!=", "<", "<=", ">", ">="):
        return _compare(op, left, right)
    return _arithmetic(op, left, right)


def _compare(op, left, right):
    if left is None or right is None:
        return None  # unknown: any comparison with NULL is unknown
    if is_number(left) and is_number(right):
        pass
    elif isinstance(left, str) and isinstance(right, str):
        pass  # lexicographic comparison
    else:
        raise StorelensError(
            "Type mismatch: cannot compare %r with %r" % (left, right))
    if op == "=":
        return left == right
    if op == "!=":
        return left != right
    if op == "<":
        return left < right
    if op == "<=":
        return left <= right
    if op == ">":
        return left > right
    return left >= right


def _arithmetic(op, left, right):
    if left is None or right is None:
        return None  # missing values propagate through arithmetic
    if not (is_number(left) and is_number(right)):
        raise StorelensError(
            "Type mismatch: arithmetic operator '%s' requires numbers, "
            "got %r and %r" % (op, left, right))
    if op == "+":
        return left + right
    if op == "-":
        return left - right
    if op == "*":
        return left * right
    if op == "/":
        if right == 0:
            raise StorelensError("Division by zero")
        return left / right
    if op == "%":
        if right == 0:
            raise StorelensError("Division by zero")
        return left % right
    raise StorelensError("Unknown operator '%s'" % op)
