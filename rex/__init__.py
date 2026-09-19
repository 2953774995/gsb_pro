"""rex - a tiny regular expression engine implemented from scratch.

Standard-library only; the ``re`` module is never used for matching.
"""

from .errors import RegexError, RegexTimeoutError
from .flags import IGNORECASE, MULTILINE, I, M
from .pattern import Pattern, Match, compile, DEFAULT_MAX_STEPS

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
]

__version__ = "0.1.0"
