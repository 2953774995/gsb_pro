"""Pattern router supporting ``/users/:id`` style path parameters."""

import re
from typing import Callable, Dict, List, Tuple

from .errors import HTTPError

Handler = Callable[..., object]

_METHODS = ("GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD")


class _Route:
    __slots__ = ("pattern", "keys", "handler")

    def __init__(self, pattern: str, keys: List[str], handler: Handler):
        self.pattern = pattern
        self.keys = keys
        self.handler = handler


def _compile(path: str) -> Tuple[re.Pattern, List[str]]:
    keys: List[str] = []
    parts = []
    for segment in path.strip("/").split("/"):
        if segment == "":
            continue
        if segment.startswith(":"):
            name = segment[1:]
            if not name:
                raise ValueError("empty path parameter in %r" % path)
            keys.append(name)
            parts.append(r"/([^/]+)")
        else:
            parts.append("/" + re.escape(segment))
    if not parts:
        parts.append("/")
        regex = re.compile(r"^/$")
    else:
        regex = re.compile(r"^" + "".join(parts) + r"$")
    return regex, keys


class Router:
    def __init__(self) -> None:
        # method -> list of registered routes (registration order).
        self._routes: Dict[str, List[_Route]] = {}
        # Method used for registration; GET implicitly serves HEAD.
        for method in _METHODS:
            self._routes[method] = []

    def add(self, method: str, path: str, handler: Handler) -> None:
        method = method.upper()
        if method not in self._routes:
            self._routes[method] = []
        pattern, keys = _compile(path)
        self._routes[method].append(_Route(pattern, keys, handler))

    def get(self, path: str) -> Callable[[Handler], Handler]:
        def decorate(handler: Handler) -> Handler:
            self.add("GET", path, handler)
            return handler
        return decorate

    def post(self, path: str) -> Callable[[Handler], Handler]:
        def decorate(handler: Handler) -> Handler:
            self.add("POST", path, handler)
            return handler
        return decorate

    def put(self, path: str) -> Callable[[Handler], Handler]:
        def decorate(handler: Handler) -> Handler:
            self.add("PUT", path, handler)
            return handler
        return decorate

    def delete(self, path: str) -> Callable[[Handler], Handler]:
        def decorate(handler: Handler) -> Handler:
            self.add("DELETE", path, handler)
            return handler
        return decorate

    def match(self, method: str, path: str) -> Tuple[Handler, Dict[str, str]]:
        """Return ``(handler, params)`` or raise 404 / 405.

        405 carries an ``Allow`` header listing every method whose
        pattern matches the path.  A registered GET implicitly handles
        HEAD as well.
        """
        method = method.upper()
        candidates = self._routes.get(method, [])
        for route in candidates:
            match = route.pattern.match(path)
            if match:
                return route.handler, dict(zip(route.keys, match.groups()))
        if method == "HEAD":
            for route in self._routes.get("GET", []):
                match = route.pattern.match(path)
                if match:
                    return route.handler, dict(zip(route.keys, match.groups()))

        # Path matched another method? -> 405, otherwise 404.
        allowed: List[str] = []
        for candidate_method, routes in self._routes.items():
            for route in routes:
                if route.pattern.match(path):
                    if candidate_method not in allowed:
                        allowed.append(candidate_method)
                    break
        if "GET" in allowed and "HEAD" not in allowed:
            allowed.append("HEAD")
        if allowed:
            raise HTTPError(
                405,
                headers={"Allow": ", ".join(sorted(allowed))},
            )
        raise HTTPError(404)
