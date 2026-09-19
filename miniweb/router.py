"""URL router with /users/:id style path parameters."""

import re

from .errors import HTTPError

_PARAM_RE = re.compile(r":([A-Za-z_][A-Za-z0-9_]*)")


def _compile(path):
    """Turn '/users/:id' into a regex plus parameter names."""
    names = []
    out = []
    pos = 0
    for m in _PARAM_RE.finditer(path):
        out.append(re.escape(path[pos:m.start()]))
        out.append("(?P<%s>[^/]+)" % m.group(1))
        names.append(m.group(1))
        pos = m.end()
    out.append(re.escape(path[pos:]))
    return re.compile("^" + "".join(out) + "$"), names


class Router(object):
    """Method + path dispatch.  Handlers: handler(request) ->
    (status, headers, body)."""

    def __init__(self):
        self._routes = []  # list of (method, regex, handler, template)

    def add(self, method, path, handler):
        regex, _ = _compile(path)
        self._routes.append((method.upper(), regex, handler, path))
        return handler

    def route(self, path, methods=("GET",)):
        def decorator(func):
            for method in methods:
                self.add(method, path, func)
            return func
        return decorator

    def get(self, path):
        return self.route(path, ("GET",))

    def post(self, path):
        return self.route(path, ("POST",))

    def put(self, path):
        return self.route(path, ("PUT",))

    def delete(self, path):
        return self.route(path, ("DELETE",))

    def dispatch(self, request):
        """Run the matching handler, filling request.path_params.

        Raises HTTPError(404) when no path matches, HTTPError(405) with
        an Allow header when the path exists for other methods.
        """
        path = request.path
        allowed = []
        for method, regex, handler, _template in self._routes:
            m = regex.match(path)
            if not m:
                continue
            if method == request.method or (
                    request.method == "HEAD" and method == "GET"):
                request.path_params = m.groupdict()
                return handler(request)
            allowed.append(method)
        if allowed:
            if "GET" in allowed and "HEAD" not in allowed:
                allowed.append("HEAD")
            raise HTTPError(405, "method not allowed",
                            headers=[("Allow", ", ".join(allowed))])
        raise HTTPError(404, "not found")

    def allowed_methods(self, path):
        allowed = []
        for method, regex, _h, _t in self._routes:
            if regex.match(path) and method not in allowed:
                allowed.append(method)
        if "GET" in allowed and "HEAD" not in allowed:
            allowed.append("HEAD")
        return allowed
