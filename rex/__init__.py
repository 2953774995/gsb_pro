"""rex -- a mini regular expression engine (standard library only)."""

from .errors import RegexError, RegexTimeoutError
from .flags import IGNORECASE, MULTILINE, I, M
from .pattern import DEFAULT_STEP_LIMIT, Match, Pattern, compile

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
    "DEFAULT_STEP_LIMIT",
    "__version__",
]
