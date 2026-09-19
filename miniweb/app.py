"""Application object: router + static files + middleware hooks."""

import sys
import traceback

from .errors import HTTPError, NotFound
from .response import Response
from .router import Router
from .static import StaticFiles


def normalize_response(result):
    """Accept a Response or a (status, headers, body) tuple."""
    if isinstance(result, Response):
        return result
    if isinstance(result, tuple):
        status, headers, body = result
        return Response(status, headers, body)
    raise TypeError("handler must return Response or (status, headers, body)")


class Application:
    """Ties together routing, static files, and middleware hooks."""

    def __init__(self, router=None, root=None):
        self.router = router or Router()
        self.static = StaticFiles(root) if root else None
        self.before_request = []
        self.after_response = []

    def add_route(self, method, path, handler):
        return self.router.add(method, path, handler)

    def route(self, method, path):
        return self.router.route(method, path)

    def get(self, path):
        return self.router.get(path)

    def post(self, path):
        return self.router.post(path)

    def put(self, path):
        return self.router.put(path)

    def delete(self, path):
        return self.router.delete(path)

    def handle(self, request):
        """Turn a Request into a Response; never raises."""
        try:
            response = None
            for hook in self.before_request:
                result = hook(request)
                if result is not None:
                    response = normalize_response(result)
                    break
            if response is None:
                response = self._dispatch(request)
        except HTTPError as exc:
            response = Response.error(exc.status, exc.message, exc.headers)
        except Exception:
            traceback.print_exc(file=sys.stderr)
            response = Response.error(500)
        for hook in self.after_response:
            result = hook(request, response)
            if result is not None:
                response = normalize_response(result)
        return response

    def _dispatch(self, request):
        try:
            handler, params = self.router.match(request.method, request.path)
        except NotFound:
            if self.static is not None:
                return self.static.handle(request)
            raise
        request.path_params = params
        return normalize_response(handler(request))
