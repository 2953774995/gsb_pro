"""tinytpl - a minimal template engine using only the Python standard library.

Supports variables (with HTML escaping and a ``raw`` filter), dotted
lookup, if/elif/else, for loops with a ``loop`` helper, comments,
template inheritance (extends/block) and includes.
"""

from .environment import Environment, Template
from .errors import TemplateNotFound, TplError
from .loader import DictLoader, FileSystemLoader

__version__ = "0.1.0"

__all__ = [
    "Template",
    "Environment",
    "TplError",
    "TemplateNotFound",
    "DictLoader",
    "FileSystemLoader",
    "__version__",
]
