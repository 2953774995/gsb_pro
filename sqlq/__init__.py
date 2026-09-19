"""sqlq - a tiny in-memory SQL query engine (standard library only)."""

from .engine import Engine, ResultSet
from .errors import SqlqError, SqlqSyntaxError
from .parser import parse, parse_script

__all__ = [
    "Engine",
    "ResultSet",
    "SqlqError",
    "SqlqSyntaxError",
    "parse",
    "parse_script",
]

__version__ = "0.1.0"
