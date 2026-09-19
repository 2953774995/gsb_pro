"""Exception hierarchy for sqlq."""


class SqlqError(Exception):
    """Base class for every sqlq error (lexing, parsing and execution)."""

    def __init__(self, message, line=None, column=None):
        self.message = message
        self.line = line
        self.column = column
        if line is not None and column is not None:
            full = "{} (line {}, column {})".format(message, line, column)
        else:
            full = message
        super().__init__(full)
