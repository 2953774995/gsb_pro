"""URL routing with method dispatch and :param path segments."""

import re

from .errors import MethodNotAllowed, NotFound

_PARAM_RE = re.compile(r"^:([A-Za-z_][A-Za-z0-9_]*)$")


def _compile_path(path):
    """Compile '/users/:id' into a regex with named groups."""
    parts = path.split("/")
    pattern = []
    for part in parts:
        m = _PARAM_RE.match(part)
        if m:
            pattern.append("(?P<%s>[^/]+)" % m.group(1))
        else:
            pattern.append(re.escape(part))
    return re.compile("^" + "/".join(pattern) + "$")


class Router:
    """Registers handlers per (method, path) and dispatches requests."""

    def __init__(self):
        self._routes = []  # (method, regex, handler, raw_path)

    def add(self, method, path, handler):
        self._routes.append((method.upper(), _compile_path(path), handler, path))
        return handler

    def route(self, method, path):
        def decorator(func):
            return self.add(method, path, func)

        return decorator

    def get(self, path):
        return self.route("GET", path)

    def post(self, path):
        return self.route("POST", path)

    def put(self, path):
        return self.route("PUT", path)

    def delete(self, path):
        return self.route("DELETE", path)

    def match(self, method, path):
        """Return (handler, path_params) or raise NotFound / MethodNotAllowed."""
        allowed = []
        for route_method, regex, handler, _ in self._routes:
            m = regex.match(path)
            if not m:
                continue
            if route_method == method or (method == "HEAD" and route_method == "GET"):
                return handler, m.groupdict()
            allowed.append(route_method)
        if allowed:
            if "GET" in allowed:
                allowed.append("HEAD")
            raise MethodNotAllowed(allowed)
        raise NotFound("no route for %s" % path)
