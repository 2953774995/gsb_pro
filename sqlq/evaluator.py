"""Scalar expression evaluation with SQL three-valued logic.

A *context* maps qualified column names to values.  It is a plain dict keyed
by both the bare column name (``"a"``) and the qualified name
(``"table.a"``).  Aggregate results are passed as a second dict keyed by the
:class:`FuncCall` node's ``id()``.
"""

from . import ast_nodes as ast
from .errors import SqlqError
from .values import NULL, is_number

# Sentinel used internally to represent SQL UNKNOWN in boolean contexts.
UNKNOWN = None


def is_true(value):
    return value is True


def evaluate(expr, row_context, aggregates=None):
    if aggregates is None:
        aggregates = {}

    if isinstance(expr, ast.Literal):
        return expr.value

    if isinstance(expr, ast.ColumnRef):
        return _lookup_column(expr, row_context)

    if isinstance(expr, ast.UnaryOp):
        value = evaluate(expr.operand, row_context, aggregates)
        if expr.op == "NOT":
            if value is None:
                return None
            if not isinstance(value, bool):
                raise SqlqError(
                    f"NOT requires a boolean operand, got {_type_label(value)}"
                )
            return not value
        if value is None:
            return None
        if expr.op == "-":
            _require_numeric(value, expr)
            return -value
        # unary plus
        _require_numeric(value, expr)
        return value

    if isinstance(expr, ast.BinaryOp):
        return _eval_binary(expr, row_context, aggregates)

    if isinstance(expr, ast.IsNull):
        value = evaluate(expr.operand, row_context, aggregates)
        result = value is None
        return (not result) if expr.negated else result

    if isinstance(expr, ast.FuncCall):
        try:
            return aggregates[id(expr)]
        except KeyError:
            raise SqlqError(
                f"aggregate {expr.name} used outside of an aggregate context"
            )

    raise SqlqError(f"cannot evaluate expression node {type(expr).__name__}")


def _lookup_column(expr, row_context):
    if expr.table is not None:
        key = f"{expr.table}.{expr.column}"
        if key in row_context:
            return row_context[key]
        # Fall back to bare name only when the table qualifier matches no
        # column at all (analyzer normally rejects this earlier).
        if expr.column in row_context:
            raise SqlqError(
                f"table qualifier {expr.table!r} does not have column {expr.column!r}"
            )
        raise SqlqError(f"unknown column {key!r}")
    if expr.column in row_context:
        return row_context[expr.column]
    raise SqlqError(f"unknown column {expr.column!r}")


def _eval_binary(expr, row_context, aggregates):
    op = expr.op
    if op == "AND":
        left = evaluate(expr.left, row_context, aggregates)
        right = evaluate(expr.right, row_context, aggregates)
        return _three_valued_and(left, right)
    if op == "OR":
        left = evaluate(expr.left, row_context, aggregates)
        right = evaluate(expr.right, row_context, aggregates)
        return _three_valued_or(left, right)

    left = evaluate(expr.left, row_context, aggregates)
    right = evaluate(expr.right, row_context, aggregates)

    if op in ("=", "!=", "<", "<=", ">", ">="):
        return _compare(op, left, right)

    # Arithmetic propagates NULL and requires numeric operands.
    if left is None or right is None:
        return None
    _require_numeric(left, expr.left)
    _require_numeric(right, expr.right)
    if op == "+":
        return left + right
    if op == "-":
        return left - right
    if op == "*":
        return left * right
    if op == "/":
        if right == 0:
            raise SqlqError("division by zero")
        # SQL real division: integer / integer yields REAL (like SQLite/PG).
        if isinstance(left, int) and isinstance(right, int) and not isinstance(right, bool):
            return left / right
        return left / right
    if op == "%":
        if right == 0:
            raise SqlqError("modulo by zero")
        if isinstance(left, float) or isinstance(right, float):
            raise SqlqError("modulo requires INTEGER operands")
        # Python % can return negatives; SQL semantics match sign of dividend.
        return abs(left) % abs(right) * (1 if left >= 0 else -1)
    raise SqlqError(f"unknown operator {op!r}")


def _compare(op, left, right):
    if left is None or right is None:
        return None  # UNKNOWN
    if op in ("=", "!="):
        try:
            equal = _sql_equal(left, right)
        except TypeError:
            raise SqlqError(
                f"cannot compare {_type_label(left)} with {_type_label(right)}"
            )
        return equal if op == "=" else not equal
    # Ordering comparisons.
    if isinstance(left, str) != isinstance(right, str):
        raise SqlqError(
            f"cannot compare {_type_label(left)} with {_type_label(right)}"
        )
    if not is_number(left) and not isinstance(left, str):
        raise SqlqError(f"cannot order value of type {_type_label(left)}")
    try:
        if left < right:
            return op == "<" or op == "<="
        if left > right:
            return op == ">" or op == ">="
        return op == "<=" or op == ">="
    except TypeError:
        raise SqlqError(
            f"cannot compare {_type_label(left)} with {_type_label(right)}"
        )


def _sql_equal(left, right):
    # Numeric cross-type equality (int vs float) works naturally.
    if isinstance(left, str) or isinstance(right, str):
        if not (isinstance(left, str) and isinstance(right, str)):
            raise TypeError("text vs non-text")
        return left == right
    return left == right


def _three_valued_and(left, right):
    _require_boolean(left)
    _require_boolean(right)
    if left is False or right is False:
        return False
    if left is None or right is None:
        return None
    return True


def _three_valued_or(left, right):
    _require_boolean(left)
    _require_boolean(right)
    if left is True or right is True:
        return True
    if left is None or right is None:
        return None
    return False


def _require_boolean(value):
    if value is not None and not isinstance(value, bool):
        raise SqlqError(
            f"logical operator requires boolean operand, got {_type_label(value)}"
        )


def _require_numeric(value, node):
    if not is_number(value):
        raise SqlqError(
            f"arithmetic requires numeric operands, got {_type_label(value)}"
        )


def _type_label(value):
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "INTEGER"
    if isinstance(value, int):
        return "INTEGER"
    if isinstance(value, float):
        return "REAL"
    if isinstance(value, str):
        return "TEXT"
    return type(value).__name__
