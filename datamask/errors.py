"""Custom exceptions for the datamask pattern engine."""


class PatternError(Exception):
    """Raised for invalid patterns or other pattern-engine errors.

    Attributes:
        message: human readable reason.
        column:  1-based column in the pattern where the problem was
                 detected, or None when not applicable.
    """

    def __init__(self, message, column=None):
        self.message = message
        self.column = column
        if column is not None:
            super().__init__("%s (column %d)" % (message, column))
        else:
            super().__init__(message)


class PatternTimeoutError(PatternError):
    """Raised when a single match attempt exceeds the step budget."""

    def __init__(self, limit):
        self.limit = limit
        super().__init__(
            "match step limit exceeded (limit=%d), "
            "possible catastrophic backtracking" % limit
        )
