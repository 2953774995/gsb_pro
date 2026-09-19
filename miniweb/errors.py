"""Exception hierarchy for miniweb.

All parsing-level failures are :class:`RequestError` and become 4xx
responses.  Anything escaping a handler becomes a generic 500.
"""

from typing import Optional


class MiniWebError(Exception):
    """Base class for every miniweb-specific error."""


class RequestError(MiniWebError):
    """The request itself was malformed or otherwise unacceptable.

    ``status`` defaults to 400; callers (e.g. oversized bodies) may use
    413.  ``close_connection`` tells the server to drop the TCP
    connection after sending the error reply because the framing cannot
    be trusted (or the body was not consumed).
    """

    def __init__(
        self,
        message: str = "Bad Request",
        status: int = 400,
        close_connection: bool = True,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.close_connection = close_connection


class HTTPError(MiniWebError):
    """Raisable from handlers/middleware to short-circuit with a status.

    A default plain-HTML body is generated unless ``body`` is given.
    """

    def __init__(
        self,
        status: int,
        message: Optional[str] = None,
        headers: Optional[dict] = None,
        body: Optional[bytes] = None,
    ) -> None:
        super().__init__(message or str(status))
        self.status = status
        self.message = message
        self.headers = headers or {}
        self.body = body
