"""minisearch: a minimal in-memory full-text search engine (stdlib only)."""

from .engine import SearchEngine
from .query import SearchError

__version__ = "0.1.0"
__all__ = ["SearchEngine", "SearchError"]
