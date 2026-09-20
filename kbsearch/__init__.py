"""kbsearch public package."""
from .engine import KBSearch
from .errors import SearchError

__all__ = ["KBSearch", "SearchError"]
__version__ = "1.0.0"
