"""Regex-free path router supporting /devices/:id parameters."""
from .errors import HTTPError

_SAFE_METHODS = ("GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS")


def split_path(path):
    return [segment for segment in path.split("/") if segment]


class Route:
    def __init__(self, method, pattern, handler):
        self.method = method.upper()
        self.pattern = pattern
        self.handler = handler
        self.segments = split_path(pattern)

    def match(self, segments):
        if len(self.segments) != len(segments):
            return None
        params = {}
        for expected, actual in zip(self.segments, segments):
            if expected.startswith(":"):
                params[expected[1:]] = actual
            elif expected != actual:
                return None
        return params


class Router:
    def __init__(self):
        self.routes = []

    def add(self, method, path, handler):
        method = method.upper()
        if method not in _SAFE_METHODS:
            raise ValueError(f"Unsupported route method: {method}")
        if not path.startswith("/"):
            raise ValueError("Route pattern must start with '/'")
        route = Route(method, path, handler)
        self.routes.append(route)
        return route

    def get(self, path, handler):
        return self.add("GET", path, handler)

    def post(self, path, handler):
        return self.add("POST", path, handler)

    def put(self, path, handler):
        return self.add("PUT", path, handler)

    def delete(self, path, handler):
        return self.add("DELETE", path, handler)

    def head(self, path, handler):
        return self.add("HEAD", path, handler)

    def options(self, path, handler):
        return self.add("OPTIONS", path, handler)

    def dispatch(self, request):
        segments = split_path(request.path)
        matched_methods = set()
        fallback_get = None
        for route in self.routes:
            params = route.match(segments)
            if params is None:
                continue
            matched_methods.add(route.method)
            if route.method == request.method:
                request.params = params
                return route.handler(request)
            if request.method == "HEAD" and route.method == "GET":
                fallback_get = route
        if matched_methods:
            if fallback_get is not None:
                request.params = fallback_get.match(segments)
                return fallback_get.handler(request)
            if "GET" in matched_methods:
                matched_methods.add("HEAD")
            raise HTTPError(405, "Method Not Allowed", {"Allow": ", ".join(sorted(matched_methods))})
        raise HTTPError(404, "Not Found")
