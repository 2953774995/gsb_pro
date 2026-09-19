"""minisearch: a mini full-text search engine (standard library only)."""

from .engine import SearchEngine, SearchResult
from .errors import SearchError

__version__ = "0.1.0"
__all__ = ["SearchEngine", "SearchResult", "SearchError", "__version__"]
