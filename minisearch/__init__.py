"""minisearch：纯标准库实现的迷你全文搜索引擎。"""

from .engine import SearchEngine
from .errors import SearchError

__all__ = ["SearchEngine", "SearchError"]
__version__ = "0.1.0"
