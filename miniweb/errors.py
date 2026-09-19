"""Exception types used by the miniweb HTTP server."""

from typing import Dict, Optional


class HTTPError(Exception):
    """An exception that maps to an HTTP error response."""

    status = 500
    reason = "Internal Server Error"

    def __init__(
        self,
        message: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        super().__init__(message or self.reason)
        self.message = message or self.reason
        self.headers = dict(headers or {})


class BadRequest(HTTPError):
    status = 400
    reason = "Bad Request"


class RequestEntityTooLarge(HTTPError):
    status = 413
    reason = "Payload Too Large"


class NotFound(HTTPError):
    status = 404
    reason = "Not Found"


class Forbidden(HTTPError):
    status = 403
    reason = "Forbidden"


class MethodNotAllowed(HTTPError):
    status = 405
    reason = "Method Not Allowed"

    def __init__(self, allow: Optional[str] = None) -> None:
        headers = {"Allow": allow} if allow else {}
        super().__init__(headers=headers)
        self.allow = allow or ""


class InternalServerError(HTTPError):
    status = 500
    reason = "Internal Server Error"
