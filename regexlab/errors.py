"""Custom exception types for regexlab."""


class RegexError(Exception):
    """Raised when a pattern cannot be parsed or compiled.

    Carries an optional ``pos`` attribute indicating the offset in the
    pattern string where the problem was detected.
    """

    def __init__(self, message, pos=None):
        self.pos = pos
        if pos is not None:
            message = "%s (at position %d)" % (message, pos)
        super().__init__(message)
