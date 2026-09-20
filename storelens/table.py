"""In-memory table storage.

Rows are stored as an ordered list of tuples aligned with the column
definitions, preserving insertion order.
"""

from .errors import StorelensError
from .types import coerce


class Table:
    def __init__(self, name, column_defs):
        self.name = name
        self.columns = list(column_defs)  # list of ColumnDef
        self.column_names = [c.name for c in self.columns]
        self._index = {c.name.lower(): i
                       for i, c in enumerate(self.columns)}
        if len(self._index) != len(self.columns):
            raise StorelensError(
                "Duplicate column name in table '%s'" % name)
        self.primary_key = None
        for c in self.columns:
            if c.primary_key:
                self.primary_key = c.name
        self.rows = []  # list of tuples

    # -- column helpers ----------------------------------------------------

    def column_index(self, name):
        idx = self._index.get(name.lower())
        if idx is None:
            raise StorelensError(
                "Unknown column '%s' in table '%s'" % (name, self.name))
        return idx

    def has_column(self, name):
        return name.lower() in self._index

    def column_type(self, name):
        return self.columns[self.column_index(name)].type_name

    # -- row operations ------------------------------------------------------

    def _check_primary_key(self, row, exclude_row=None):
        if self.primary_key is None:
            return
        idx = self.column_index(self.primary_key)
        value = row[idx]
        if value is None:
            raise StorelensError(
                "Primary key column '%s' cannot be NULL" % self.primary_key)
        for existing in self.rows:
            if existing is exclude_row:
                continue
            if existing[idx] == value:
                raise StorelensError(
                    "Primary key violation: duplicate value %r for column "
                    "'%s' in table '%s'"
                    % (value, self.primary_key, self.name))

    def make_row(self, values, columns=None):
        """Build a full row tuple from values for the given column names.

        *columns* of None means values are given for all columns in order.
        Missing columns are filled with None. Values are type-coerced.
        """
        if columns is None:
            if len(values) != len(self.columns):
                raise StorelensError(
                    "INSERT into table '%s' expects %d values, got %d"
                    % (self.name, len(self.columns), len(values)))
            pairs = zip(self.column_names, values)
        else:
            if len(values) != len(columns):
                raise StorelensError(
                    "INSERT into table '%s' has %d columns but %d values"
                    % (self.name, len(columns), len(values)))
            pairs = zip(columns, values)
        row = [None] * len(self.columns)
        for col_name, value in pairs:
            idx = self.column_index(col_name)
            col = self.columns[idx]
            row[idx] = coerce(value, col.type_name, col.name)
        return tuple(row)

    def insert_row(self, row):
        self._check_primary_key(row)
        self.rows.append(row)

    def coerce_value(self, col_name, value):
        idx = self.column_index(col_name)
        col = self.columns[idx]
        return coerce(value, col.type_name, col.name)

    def check_row_primary_key(self, row, exclude_row=None):
        self._check_primary_key(row, exclude_row=exclude_row)
