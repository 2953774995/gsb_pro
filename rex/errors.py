"""Custom exception types for the rex regex engine."""


class RegexError(Exception):
    """Base error for rex.

    Raised for invalid patterns (with a human readable reason and the
    1-based column where the problem was detected) and as the base class
    of :class:`RegexTimeoutError`.
    """

    def __init__(self, message, pos=None):
        self.message = message
        self.pos = pos
        if pos is not None:
            super().__init__("{} (at column {})".format(message, pos + 1))
        else:
            super().__init__(message)


class RegexTimeoutError(RegexError):
    """Raised when a single match attempt exceeds the step budget."""

    def __init__(self, steps, limit):
        self.steps = steps
        self.limit = limit
        super().__init__(
            "match aborted: step limit exceeded ({} steps, limit {})".format(
                steps, limit
            )
        )
