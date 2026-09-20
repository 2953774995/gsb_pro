"""Expression evaluation with SQL-style three-valued logic.

Truth values are True / False / None (unknown). Any comparison involving a
missing value (None) yields None. Arithmetic propagates None. Aggregates
skip missing values; GROUP BY treats all missing values as one group.
"""

from . import astnodes as ast
from .errors import StorelensError
from .tables import is_number


def evaluate(expr, row, table, group=None):
    """Evaluate an expression.

    row   -- the current row dict (or representative row of a group)
    table -- the Table the row belongs to (for column validation)
    group -- list of rows when evaluating in a grouped/aggregate context,
             None for plain per-row evaluation
    """
    if isinstance(expr, ast.Literal):
        return expr.value
    if isinstance(expr, ast.Column):
        if not table.has_column(expr.name):
            raise StorelensError(
                "table %s has no column named %s" % (table.name, expr.name))
        return row[expr.name]
    if isinstance(expr, ast.Star):
        raise StorelensError("'*' is only allowed in SELECT * or COUNT(*)")
    if isinstance(expr, ast.Unary):
        return _eval_unary(expr, row, table, group)
    if isinstance(expr, ast.Binary):
        return _eval_binary(expr, row, table, group)
    if isinstance(expr, ast.IsNull):
        value = evaluate(expr.operand, row, table, group)
        result = value is None
        return (not result) if expr.negated else result
    if isinstance(expr, ast.FuncCall):
        return _eval_aggregate(expr, row, table, group)
    raise StorelensError("cannot evaluate expression %r" % (expr,))


def _eval_unary(expr, row, table, group):
    value = evaluate(expr.operand, row, table, group)
    if expr.op == "NOT":
        if value is None:
            return None
        return not _truthy(value)
    if expr.op == "-":
        if value is None:
            return None
        if not is_number(value):
            raise StorelensError(
                "cannot negate non-numeric value %r" % (value,))
        return -value
    raise StorelensError("unknown unary operator %r" % expr.op)


def _eval_binary(expr, row, table, group):
    op = expr.op
    if op == "AND":
        left = evaluate(expr.left, row, table, group)
        if left is not None and not _truthy(left):
            return False
        right = evaluate(expr.right, row, table, group)
        if right is not None and not _truthy(right):
            return False
        if left is None or right is None:
            return None
        return True
    if op == "OR":
        left = evaluate(expr.left, row, table, group)
        if left is not None and _truthy(left):
            return True
        right = evaluate(expr.right, row, table, group)
        if right is not None and _truthy(right):
            return True
        if left is None or right is None:
            return None
        return False

    left = evaluate(expr.left, row, table, group)
    right = evaluate(expr.right, row, table, group)

    if op in ("+", "-", "*", "/"):
        if left is None or right is None:
            return None
        if not (is_number(left) and is_number(right)):
            raise StorelensError(
                "arithmetic operator %r requires numbers, got %r and %r"
                % (op, left, right))
        if op == "+":
            return left + right
        if op == "-":
            return left - right
        if op == "*":
            return left * right
        if right == 0:
            raise StorelensError("division by zero")
        return left / right

    # comparisons: any missing operand makes the result unknown
    if left is None or right is None:
        return None
    if is_number(left) and is_number(right):
        pass
    elif isinstance(left, str) and isinstance(right, str):
        pass
    else:
        raise StorelensError(
            "cannot compare %s value %r with %s value %r"
            % (type(left).__name__, left, type(right).__name__, right))
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
    if op == ">=":
        return left >= right
    raise StorelensError("unknown operator %r" % op)


def _eval_aggregate(expr, row, table, group):
    if group is None:
        raise StorelensError(
            "aggregate function %s is not allowed in this context" % expr.name)
    if isinstance(expr.arg, ast.Star):
        if expr.name != "COUNT":
            raise StorelensError("%s(*) is not supported; use COUNT(*)"
                                 % expr.name)
        return len(group)
    values = []
    for member in group:
        value = evaluate(expr.arg, member, table, None)
        if value is not None:
            values.append(value)
    if expr.name == "COUNT":
        return len(values)
    if expr.name in ("SUM", "AVG"):
        for value in values:
            if not is_number(value):
                raise StorelensError(
                    "%s requires a numeric column, got value %r"
                    % (expr.name, value))
        if expr.name == "SUM":
            return sum(values) if values else None
        return (sum(values) / len(values)) if values else None
    if expr.name == "MIN":
        return _min_max(values, min)
    if expr.name == "MAX":
        return _min_max(values, max)
    raise StorelensError("unknown aggregate function %s" % expr.name)


def _min_max(values, func):
    if not values:
        return None
    first = values[0]
    for value in values[1:]:
        if is_number(first) != is_number(value):
            raise StorelensError(
                "cannot compare mixed types %r and %r" % (first, value))
    return func(values)


def _truthy(value):
    if isinstance(value, str):
        raise StorelensError(
            "string value %r cannot be used as a boolean" % (value,))
    if is_number(value):
        return value != 0
    if isinstance(value, bool):
        return value
    raise StorelensError("value %r cannot be used as a boolean" % (value,))
