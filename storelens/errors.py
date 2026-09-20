"""Storelens error types."""


class StorelensError(Exception):
    """Raised for any syntax, semantic, or runtime error in storelens.

    The message always describes what went wrong; when available it also
    carries line/column information about the offending input.
    """

    def __init__(self, message, line=None, col=None):
        self.message = message
        self.line = line
        self.col = col
        if line is not None and col is not None:
            super().__init__("%s (line %d, column %d)" % (message, line, col))
        else:
            super().__init__(message)
