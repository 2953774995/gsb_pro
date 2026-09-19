"""miniweb: a minimal HTTP/1.1 server built from raw sockets."""

from .app import MiniWeb
from .config import Config
from .errors import HTTPError, MiniWebError, RequestError
from .request import Request
from .response import Response, error_response
from .router import Router
from .server import HttpServer
from .static import guess_mime, serve_static

__all__ = [
    "MiniWeb",
    "Config",
    "HttpServer",
    "Router",
    "Request",
    "Response",
    "HTTPError",
    "RequestError",
    "MiniWebError",
    "error_response",
    "serve_static",
    "guess_mime",
]

__version__ = "0.1.0"
