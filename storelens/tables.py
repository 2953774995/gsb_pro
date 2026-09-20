"""In-memory table storage and the INTEGER / REAL / TEXT type system.

Rows are stored as an ordered list of dicts (column name -> value).
Missing values are represented by None. A primary key column (if defined)
must not contain duplicate or NULL values.
"""

from .errors import StorelensError

TYPES = ("INTEGER", "REAL", "TEXT")


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _show(value):
    return "%s value %r" % (type(value).__name__, value)


def coerce_value(col_type, col_name, value):
    """Validate and coerce a Python value for a column of the given type.

    None passes through for every type (missing value). Raises
    StorelensError on type mismatch.
    """
    if value is None:
        return None
    if col_type == "INTEGER":
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        raise StorelensError(
            "type mismatch: column %s is INTEGER, got %s"
            % (col_name, _show(value)))
    if col_type == "REAL":
        if is_number(value):
            return float(value)
        raise StorelensError(
            "type mismatch: column %s is REAL, got %s"
            % (col_name, _show(value)))
    if col_type == "TEXT":
        if isinstance(value, str):
            return value
        raise StorelensError(
            "type mismatch: column %s is TEXT, got %s"
            % (col_name, _show(value)))
    raise StorelensError("unknown column type %r" % (col_type,))


class Column:
    __slots__ = ("name", "type", "primary_key")

    def __init__(self, name, type_, primary_key=False):
        self.name = name
        self.type = type_
        self.primary_key = primary_key


class Table:
    def __init__(self, name, columns):
        self.name = name
        self.columns = list(columns)          # list of Column, ordered
        self.rows = []                        # list of dict, insertion order
        pk_cols = [c for c in self.columns if c.primary_key]
        if len(pk_cols) > 1:
            raise StorelensError(
                "table %s: only one PRIMARY KEY column is supported" % name)
        self.pk_column = pk_cols[0].name if pk_cols else None

    @property
    def column_names(self):
        return [c.name for c in self.columns]

    def get_column(self, name):
        for c in self.columns:
            if c.name == name:
                return c
        raise StorelensError(
            "table %s has no column named %s" % (self.name, name))

    def has_column(self, name):
        return any(c.name == name for c in self.columns)

    def coerce_row(self, values):
        """Coerce a {column: value} mapping into a stored row dict.

        Missing columns become None; unknown columns are an error.
        """
        for key in values:
            if not self.has_column(key):
                raise StorelensError(
                    "table %s has no column named %s" % (self.name, key))
        row = {}
        for col in self.columns:
            row[col.name] = coerce_value(
                col.type, col.name, values.get(col.name))
        return row

    def check_primary_key(self, row, ignore_index=None):
        if self.pk_column is None:
            return
        value = row[self.pk_column]
        if value is None:
            raise StorelensError(
                "primary key column %s of table %s must not be NULL"
                % (self.pk_column, self.name))
        for idx, existing in enumerate(self.rows):
            if ignore_index is not None and idx == ignore_index:
                continue
            if existing[self.pk_column] == value:
                raise StorelensError(
                    "primary key violation: duplicate value %r in column %s "
                    "of table %s" % (value, self.pk_column, self.name))

    def insert_row(self, values):
        row = self.coerce_row(values)
        self.check_primary_key(row)
        self.rows.append(row)
        return row
