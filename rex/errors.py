"""Custom exception types for the rex regex engine."""


class RegexError(Exception):
    """Raised when a pattern is invalid or a match cannot be performed.

    Carries a human readable reason plus the 0-based offset in the pattern
    where the problem was detected (when known). The string representation
    includes a 1-based column number.
    """

    def __init__(self, message, pos=None):
        self.message = message
        self.pos = pos
        if pos is not None:
            super().__init__("{} (at column {})".format(message, pos + 1))
        else:
            super().__init__(message)


class RegexTimeoutError(RegexError):
    """Raised when a single match attempt exceeds the configured step budget."""

    def __init__(self, message="match exceeded the configured step limit", pos=None):
        super().__init__(message, pos)
