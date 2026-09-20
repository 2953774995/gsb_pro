"""Column types and value coercion rules.

storelens supports three column types: INTEGER, REAL and TEXT.
Values may also be None, representing a missing (NULL) value.
"""

from .errors import StorelensError

TYPE_NAMES = ("INTEGER", "REAL", "TEXT")


def coerce(value, type_name, column_name):
    """Coerce *value* into the column type or raise StorelensError.

    None passes through for every type (missing value).
    """
    if value is None:
        return None
    if type_name == "INTEGER":
        if isinstance(value, bool):
            pass  # fall through to error
        elif isinstance(value, int):
            return value
        elif isinstance(value, float) and value.is_integer():
            return int(value)
        raise StorelensError(
            "Type mismatch: value %r cannot be stored in INTEGER column "
            "'%s'" % (value, column_name))
    if type_name == "REAL":
        if isinstance(value, bool):
            pass
        elif isinstance(value, (int, float)):
            return float(value)
        raise StorelensError(
            "Type mismatch: value %r cannot be stored in REAL column "
            "'%s'" % (value, column_name))
    if type_name == "TEXT":
        if isinstance(value, str):
            return value
        raise StorelensError(
            "Type mismatch: value %r cannot be stored in TEXT column "
            "'%s'" % (value, column_name))
    raise StorelensError("Unknown column type %r" % type_name)


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)
