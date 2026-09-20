"""Domain-specific exceptions for kbsearch."""


class SearchError(ValueError):
    """Raised when a query cannot be parsed or executed.

    The message always contains a human-readable reason.  It inherits from
    :class:`ValueError`, so callers may catch either the specific error or a
    standard Python error.
    """
