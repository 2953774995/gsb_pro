"""miniweb: a small HTTP/1.1 server built from Python sockets."""

from .application import Application
from .errors import (
    BadRequest,
    Forbidden,
    HTTPError,
    InternalServerError,
    MethodNotAllowed,
    NotFound,
    RequestEntityTooLarge,
)
from .request import Request
from .response import Response, default_error_page, redirect
from .router import Router
from .server import Server
from .static import StaticFiles, guess_mime

__all__ = [
    "Application",
    "BadRequest",
    "Forbidden",
    "HTTPError",
    "InternalServerError",
    "MethodNotAllowed",
    "NotFound",
    "Request",
    "RequestEntityTooLarge",
    "Response",
    "Router",
    "Server",
    "StaticFiles",
    "default_error_page",
    "guess_mime",
    "redirect",
]
