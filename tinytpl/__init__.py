"""tinytpl —— 仅依赖标准库的迷你模板引擎。

支持变量输出（HTML 转义 / raw）、点号取值、if/elif/else、for 循环
（含 loop.index/first/last）、注释、表达式求值、模板继承
（extends/block）与包含（include）。
"""

from .environment import Environment
from .errors import TplError
from .loader import DictLoader, FileSystemLoader
from .template import Template

__version__ = "0.1.0"
__all__ = [
    "Template",
    "Environment",
    "DictLoader",
    "FileSystemLoader",
    "TplError",
    "__version__",
]
