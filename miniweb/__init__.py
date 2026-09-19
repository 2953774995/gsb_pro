"""miniweb -- a minimal HTTP/1.1 web server built on the Python standard
library only (socket + threading).  No http.server anywhere."""

from .app import Application
from .errors import HTTPError, RequestError
from .request import Headers, Request
from .response import build_response
from .router import Router
from .server import HTTPServer
from .staticfiles import StaticFiles

__version__ = "1.0.0"

__all__ = [
    "Application", "HTTPServer", "Router", "StaticFiles",
    "Request", "Headers", "HTTPError", "RequestError",
    "build_response", "__version__",
]
