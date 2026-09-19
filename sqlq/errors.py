"""Exception hierarchy for sqlq."""


class SqlqError(Exception):
    """Base class for every error raised by sqlq.

    The optional ``line``/``column`` identify the offending position in the
    source SQL (1-based).  They may be ``None`` when the error is not tied to
    a concrete token (e.g. an unknown table referenced during planning).
    """

    def __init__(self, message, line=None, column=None):
        self.message = message
        self.line = line
        self.column = column
        if line is not None and column is not None:
            full = f"{message} (line {line}, column {column})"
        else:
            full = message
        super().__init__(full)


class SqlqSyntaxError(SqlqError):
    """Raised for lexing/parsing problems (invalid token, bad grammar)."""
