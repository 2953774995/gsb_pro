"""regexlab -- a mini regular expression engine written from scratch.

Only the Python standard library is used, and the ``re`` module is
*not* used for matching: parsing, the AST and the backtracking engine
are all implemented in this package.
"""

from .core import (Match, Pattern, RegexError, compile, findall, finditer,
                   fullmatch, match, purge, search)

__version__ = "0.1.0"
__all__ = ["Match", "Pattern", "RegexError", "compile", "match", "search",
           "fullmatch", "findall", "finditer", "purge", "__version__"]
