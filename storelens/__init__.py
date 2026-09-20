"""storelens -- a local, offline sales-data analysis tool.

Pure Python standard library. Provides a small SQL-like query language
over in-memory datasets loaded from JSON exports.
"""

from .engine import Engine, Result
from .errors import StorelensError

__all__ = ["Engine", "Result", "StorelensError"]
__version__ = "1.0.0"
