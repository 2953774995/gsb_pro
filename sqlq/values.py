"""Data type primitives shared by every layer of the engine."""

INTEGER = "INTEGER"
REAL = "REAL"
TEXT = "TEXT"

# The canonical NULL marker.  In SQL NULL means "unknown" and is distinct from
# every Python value (including ``None`` semantics used here deliberately).
NULL = None

TYPE_NAMES = (INTEGER, REAL, TEXT)

# Numeric promotion order used for mixed arithmetic.
_NUMERIC_PROMOTION = {INTEGER: 0, REAL: 1}


def numeric_common_type(left_type, right_type):
    """Return the numeric result type of combining ``left_type``/``right_type``.

    Any REAL operand forces REAL; otherwise the result is INTEGER.
    """
    if left_type not in _NUMERIC_PROMOTION or right_type not in _NUMERIC_PROMOTION:
        return None
    if left_type == REAL or right_type == REAL:
        return REAL
    return INTEGER


def is_number(value):
    # bool is intentionally excluded even though it subclasses int.
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def type_name_of(value):
    """Return the SQL type name of a concrete Python value."""
    if value is NULL:
        return NULL
    if isinstance(value, bool):
        return INTEGER
    if isinstance(value, int):
        return INTEGER
    if isinstance(value, float):
        return REAL
    if isinstance(value, str):
        return TEXT
    return None


def coerce_for_column(value, column_type):
    """Validate/coerce a literal value against a declared column type.

    Integer literals are widened to REAL for REAL columns.  Anything that does
    not match the declared type raises ``SqlqError`` rather than being silently
    stored.
    """
    from .errors import SqlqError

    if value is NULL:
        return NULL
    if column_type == INTEGER:
        if isinstance(value, bool) or not isinstance(value, int):
            raise SqlqError(
                f"type mismatch: expected INTEGER for column value, got {type_name_of(value) or type(value).__name__}"
            )
        return value
    if column_type == REAL:
        if isinstance(value, bool):
            raise SqlqError("type mismatch: bool cannot be stored as REAL")
        if isinstance(value, float):
            return value
        if isinstance(value, int):
            return float(value)
        raise SqlqError(
            f"type mismatch: expected REAL for column value, got {type_name_of(value) or type(value).__name__}"
        )
    if column_type == TEXT:
        if not isinstance(value, str):
            raise SqlqError(
                f"type mismatch: expected TEXT for column value, got {type_name_of(value) or type(value).__name__}"
            )
        return value
    raise SqlqError(f"unknown column type: {column_type}")


def sql_repr(value):
    """Render a scalar for CLI output."""
    if value is NULL:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)
