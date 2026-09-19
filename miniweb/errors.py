"""Shared exception types for miniweb."""


class HTTPError(Exception):
    """An error that should be turned into an HTTP error response."""

    def __init__(self, status=400, message="", headers=None):
        super().__init__(message or "HTTP error %d" % status)
        self.status = status
        self.message = message or "HTTP error %d" % status
        self.headers = list(headers) if headers else []


class RequestError(HTTPError):
    """Raised while parsing a request; the connection is closed afterwards."""

    def __init__(self, status=400, message="Bad Request"):
        super().__init__(status, message)
