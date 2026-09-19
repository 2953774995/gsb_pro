"""HTTP error types used across miniweb."""


class HTTPError(Exception):
    """An error that maps directly to an HTTP response status."""

    status = 500

    def __init__(self, message=None, headers=None):
        super().__init__(message or "")
        self.message = message
        self.headers = dict(headers or {})


class BadRequest(HTTPError):
    status = 400


class Forbidden(HTTPError):
    status = 403


class NotFound(HTTPError):
    status = 404


class MethodNotAllowed(HTTPError):
    status = 405

    def __init__(self, allowed, message=None):
        self.allowed = sorted(set(allowed))
        super().__init__(message, headers={"Allow": ", ".join(self.allowed)})


class PayloadTooLarge(HTTPError):
    status = 413


class ConnectionClosed(Exception):
    """Raised when the peer closes the connection mid-request (or idles out)."""
