"""Application object: router + static files + middleware hooks."""

import sys
import traceback

from .errors import HTTPError
from .response import default_error_page
from .router import Router
from .staticfiles import StaticFiles


class Application(object):
    """Glues routing, static files and middleware together.

    handle(request) -> (status, headers, body).  Never lets an
    exception escape: anything unexpected becomes a 500 without
    leaking tracebacks to the client (they go to stderr instead).
    """

    def __init__(self, router=None, static_root=None):
        self.router = router or Router()
        self.static = StaticFiles(static_root) if static_root else None
        self._before = []
        self._after = []

    # -- routing delegates ----------------------------------------------------
    def add_route(self, method, path, handler):
        return self.router.add(method, path, handler)

    def route(self, path, methods=("GET",)):
        return self.router.route(path, methods)

    def get(self, path):
        return self.router.get(path)

    def post(self, path):
        return self.router.post(path)

    def put(self, path):
        return self.router.put(path)

    def delete(self, path):
        return self.router.delete(path)

    # -- middleware -------------------------------------------------------------
    def before_request(self, func):
        """Hook: func(request) -> None, or a (status, headers, body)
        tuple to short-circuit the request."""
        self._before.append(func)
        return func

    def after_response(self, func):
        """Hook: func(request, response_tuple) -> replacement tuple or None."""
        self._after.append(func)
        return func

    # -- main entry ---------------------------------------------------------------
    def handle(self, request):
        try:
            for hook in self._before:
                result = hook(request)
                if result is not None:
                    return self._finalize(request, result)

            response = self._dispatch(request)
            return self._finalize(request, response)
        except HTTPError as exc:
            body = default_error_page(exc.status, exc.message) \
                if exc.status >= 400 else exc.message
            return exc.status, exc.headers, body
        except Exception:
            traceback.print_exc(file=sys.stderr)
            return 500, [], None

    def _finalize(self, request, response):
        for hook in self._after:
            replacement = hook(request, response)
            if replacement is not None:
                response = replacement
        return response

    def _dispatch(self, request):
        try:
            return self.router.dispatch(request)
        except HTTPError as exc:
            if exc.status == 404 and self.static is not None:
                return self.static.handle(request)
            raise
