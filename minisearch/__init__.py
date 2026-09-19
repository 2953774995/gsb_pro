"""minisearch: a tiny in-memory full-text search engine (stdlib only)."""

from .engine import SearchEngine
from .errors import SearchError

__all__ = ["SearchEngine", "SearchError"]
__version__ = "0.1.0"
