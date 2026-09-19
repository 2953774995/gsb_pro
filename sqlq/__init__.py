"""sqlq: a tiny in-memory SQL query engine (standard library only)."""

from .errors import SqlqError
from .executor import Engine, QueryResult

__version__ = "0.1.0"

__all__ = ["Engine", "QueryResult", "SqlqError"]
