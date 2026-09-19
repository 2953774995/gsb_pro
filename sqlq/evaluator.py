"""Expression evaluation with SQL three-valued logic."""

from . import ast_nodes as ast
from .errors import SqlqError


# Sentinel returned by grouped contexts for columns that are neither grouping
# columns nor arguments of an aggregate (such expressions must be rejected
# during semantic validation before evaluation).
MISSING = object()


class EvalContext:
    """Interface implemented by row and aggregate-group scopes."""

    def get_column(self, column):
        raise NotImplementedError

    def get_aggregate(self, aggregate):
        raise NotImplementedError


def evaluate(node, context):
    if isinstance(node, ast.Literal):
        return node.value

    if isinstance(node, ast.Column):
        return context.get_column(node)

    if isinstance(node, ast.Aggregate):
        return context.get_aggregate(node)

    if isinstance(node, ast.UnaryOp):
        value = evaluate(node.operand, context)
        if value is None:
            return None
        if node.op == "NOT":
            if not isinstance(value, bool):
                raise SqlqError("NOT requires a boolean operand")
            return not value
        if node.op == "-":
            _require_numeric(value, "unary minus")
            return -value
        if node.op == "+":
            _require_numeric(value, "unary plus")
            return value

    if isinstance(node, ast.BinaryOp):
        return _eval_binary(node, context)

    if isinstance(node, ast.IsNull):
        value = evaluate(node.operand, context)
        result = value is None
        return (not result) if node.negated else result

    raise SqlqError("cannot evaluate expression node {}".format(type(node)))


def _eval_binary(node, context):
    op = node.op

    # Logical operators: SQL three-valued logic.
    if op == "AND":
        left = evaluate(node.left, context)
        right = evaluate(node.right, context)
        if left is False or right is False:
            return False
        if left is None or right is None:
            return None
        return bool(left and right)

    if op == "OR":
        left = evaluate(node.left, context)
        right = evaluate(node.right, context)
        if left is True or right is True:
            return True
        if left is None or right is None:
            return None
        return bool(left or right)

    left = evaluate(node.left, context)
    right = evaluate(node.right, context)

    if op in ("+", "-", "*", "/"):
        if left is None or right is None:
            return None
        _require_numeric(left, "arithmetic")
        _require_numeric(right, "arithmetic")
        if op == "+":
            return left + right
        if op == "-":
            return left - right
        if op == "*":
            return left * right
        if right == 0:
            raise SqlqError("division by zero")
        return left / right

    # Comparisons: NULL on either side yields NULL (unknown).
    if left is None or right is None:
        return None

    if isinstance(left, bool) or isinstance(right, bool):
        raise SqlqError("booleans cannot be compared")

    if isinstance(left, str) != isinstance(right, str) or \
            _is_number(left) != _is_number(right):
        raise SqlqError(
            "cannot compare {} with {}".format(type_name(left),
                                               type_name(right)))

    if op == "=":
        return left == right
    if op == "!=":
        return left != right

    order = (left > right) - (left < right)
    if op == "<":
        return order < 0
    if op == "<=":
        return order <= 0
    if op == ">":
        return order > 0
    if op == ">=":
        return order >= 0

    raise SqlqError("unknown operator '{}'".format(op))


def truthy(value):
    """WHERE/HAVING match: only an explicit True passes; False/NULL fail."""
    return value is True


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _require_numeric(value, operation):
    if not _is_number(value):
        raise SqlqError("{} requires a numeric value, got {}"
                        .format(operation, type_name(value)))


def type_name(value):
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "INTEGER"
    if isinstance(value, float):
        return "REAL"
    if isinstance(value, str):
        return "TEXT"
    return type(value).__name__


def expr_to_sql(node):
    """Render a default output column name for an expression."""
    if isinstance(node, ast.Column):
        return node.table + "." + node.name if node.table else node.name
    if isinstance(node, ast.Literal):
        if node.value is None:
            return "NULL"
        if isinstance(node.value, str):
            return "'" + node.value.replace("'", "''") + "'"
        return str(node.value)
    if isinstance(node, ast.Star):
        return "*"
    if isinstance(node, ast.IsNull):
        suffix = " IS NOT NULL" if node.negated else " IS NULL"
        return expr_to_sql(node.operand) + suffix
    if isinstance(node, ast.UnaryOp):
        if node.op == "NOT":
            return "NOT " + expr_to_sql(node.operand)
        return node.op + expr_to_sql(node.operand)
    if isinstance(node, ast.Aggregate):
        if node.star:
            return "COUNT(*)"
        prefix = node.name + "(DISTINCT " if node.distinct else node.name + "("
        return prefix + expr_to_sql(node.arg) + ")"
    if isinstance(node, ast.BinaryOp):
        return "{} {} {}".format(expr_to_sql(node.left), node.op,
                                 expr_to_sql(node.right))
    return "?"
