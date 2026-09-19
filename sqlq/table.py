"""In-memory relational table storage."""

from .errors import SqlqError
from .values import INTEGER, REAL, TEXT


class Column:
    __slots__ = ("name", "data_type", "primary_key", "not_null")

    def __init__(self, name, data_type, primary_key=False, not_null=False):
        self.name = name
        self.data_type = data_type
        self.primary_key = primary_key
        self.not_null = not_null or primary_key


class Table:
    """An ordered collection of rows.

    Each row is a tuple aligned with :attr:`columns`.  Duplicate column names
    are rejected at creation time.
    """

    def __init__(self, name, column_defs):
        self.name = name
        names = [c.name for c in column_defs]
        if len(set(names)) != len(names):
            raise SqlqError(f"duplicate column name in table {name!r}")
        pks = [c.name for c in column_defs if c.primary_key]
        if len(pks) > 1:
            raise SqlqError(
                f"table {name!r} declares more than one PRIMARY KEY column: {pks}"
            )
        self.columns = [
            Column(c.name, c.data_type, c.primary_key, getattr(c, "not_null", False))
            for c in column_defs
        ]
        self.rows = []

    @property
    def column_names(self):
        return [c.name for c in self.columns]

    def column(self, name):
        for col in self.columns:
            if col.name == name:
                return col
        return None

    @property
    def primary_key(self):
        for col in self.columns:
            if col.primary_key:
                return col
        return None

    def index(self, name):
        for i, col in enumerate(self.columns):
            if col.name == name:
                return i
        raise SqlqError(f"unknown column {name!r} in table {self.name!r}")
