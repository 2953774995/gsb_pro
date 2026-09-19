r"""rex -- a mini regular-expression engine in pure Python.

Public API::

    import rex
    p = rex.compile(r"(?P<word>\w+)", flags=rex.IGNORECASE)
    m = p.search("hello world")
"""
from .errors import RegexError, RegexTimeoutError
from .matcher import IGNORECASE, MULTILINE
from .pattern import DEFAULT_MAX_STEPS, Match, Pattern, compile

# Familiar short aliases, mirroring the stdlib `re` module.
I = IGNORECASE
M = MULTILINE

__version__ = "0.1.0"

__all__ = [
    "compile",
    "Pattern",
    "Match",
    "RegexError",
    "RegexTimeoutError",
    "IGNORECASE",
    "MULTILINE",
    "I",
    "M",
    "DEFAULT_MAX_STEPS",
    "__version__",
]
