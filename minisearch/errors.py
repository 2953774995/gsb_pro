"""Exception types for minisearch."""


class SearchError(Exception):
    """Raised when a query cannot be parsed or executed.

    The exception message always carries a human readable reason.
    """
