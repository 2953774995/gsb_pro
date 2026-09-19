"""Custom exceptions for the rex regex engine."""


class RegexError(Exception):
    """Raised for any regex compilation or matching error.

    ``pos`` is the 0-based offset into the pattern where the problem was
    detected; the rendered message reports a 1-based column number.
    """

    def __init__(self, message, pos=None):
        self.message = message
        self.pos = pos
        if pos is not None:
            super().__init__("{} at column {}".format(message, pos + 1))
        else:
            super().__init__(message)


class RegexTimeoutError(RegexError):
    """Raised when a single match operation exceeds its step budget."""
