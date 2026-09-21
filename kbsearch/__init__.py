"""kbsearch: offline after-sales knowledge-base retrieval (stdlib only)."""

from .core import KBSearch
from .errors import SearchError
from .synonyms import SynonymMap
from .tokenizer import Tokenizer

__all__ = ["KBSearch", "SearchError", "SynonymMap", "Tokenizer"]
__version__ = "1.0.0"
