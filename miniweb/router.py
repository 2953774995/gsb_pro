"""Small pattern router."""

from __future__ import annotations

import re
from typing import Callable, Dict, List, Tuple
from urllib.parse import unquote

from .errors import BadRequest, MethodNotAllowed, NotFound

Handler = Callable[["Request"], object]

_METHOD_ORDER = ("GET", "HEAD", "POST", "PUT", "DELETE", "PATCH", "OPTIONS")


def _split_path(path: str) -> List[str]:
    return [part for part in path.split("/") if part]


def _compile(path: str) -> Tuple[re.Pattern, List[str]]:
    parts = _split_path(path)
    names: List[str] = []
    regex_parts: List[str] = []
    for part in parts:
        if part.startswith(":"):
            name = part[1:]
            if not name or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                raise ValueError(f"Invalid path parameter: {part}")
            if name in names:
                raise ValueError(f"Duplicate path parameter: {name}")
            names.append(name)
            regex_parts.append(r"/([^/]+)")
        else:
            regex_parts.append("/" + re.escape(part))
    if not path or path == "/":
        return re.compile(r"^/$"), names
    return re.compile(r"^" + "".join(regex_parts) + r"$"), names


class Route:
    def __init__(self, path: str, method: str, handler: Handler) -> None:
        self.path = path
        self.method = method.upper()
        self.handler = handler
        self.regex, self.params = _compile(path)


class Router:
    def __init__(self) -> None:
        self.routes: List[Route] = []

    def add(self, method: str, path: str, handler: Handler) -> None:
        self.routes.append(Route(path, method.upper(), handler))

    def get(self, path: str) -> Callable[[Handler], Handler]:
        def decorator(func: Handler) -> Handler:
            self.add("GET", path, func)
            return func

        return decorator

    def post(self, path: str) -> Callable[[Handler], Handler]:
        def decorator(func: Handler) -> Handler:
            self.add("POST", path, func)
            return func

        return decorator

    def put(self, path: str) -> Callable[[Handler], Handler]:
        def decorator(func: Handler) -> Handler:
            self.add("PUT", path, func)
            return func

        return decorator

    def delete(self, path: str) -> Callable[[Handler], Handler]:
        def decorator(func: Handler) -> Handler:
            self.add("DELETE", path, func)
            return func

        return decorator

    def match(self, method: str, path: str) -> Tuple[Handler, Dict[str, str]]:
        matched_methods: List[str] = []
        method = method.upper()
        for route in self.routes:
            match = route.regex.match(path)
            if not match:
                continue
            matched_methods.append(route.method)
            if route.method == method:
                values = match.groups()
                try:
                    decoded = [unquote(value, errors="strict") for value in values]
                except UnicodeDecodeError as exc:
                    raise BadRequest(
                        "Invalid percent-encoding in path parameter"
                    ) from exc
                return route.handler, dict(zip(route.params, decoded))

        # A GET resource is also addressable by HEAD.
        if method == "HEAD":
            for route in self.routes:
                match = route.regex.match(path)
                if match and route.method == "GET":
                    values = match.groups()
                    try:
                        decoded = [unquote(value, errors="strict") for value in values]
                    except UnicodeDecodeError as exc:
                        raise BadRequest(
                            "Invalid percent-encoding in path parameter"
                        ) from exc
                    return route.handler, dict(zip(route.params, decoded))

        if matched_methods:
            allow = set(matched_methods)
            if "GET" in allow:
                allow.add("HEAD")
            ordered = [m for m in _METHOD_ORDER if m in allow] + sorted(
                allow.difference(_METHOD_ORDER)
            )
            raise MethodNotAllowed(", ".join(ordered))
        raise NotFound()

    def has_path(self, path: str) -> bool:
        return any(route.regex.match(path) for route in self.routes)

    def allowed_methods(self, path: str) -> str:
        methods = {
            route.method for route in self.routes if route.regex.match(path)
        }
        if "GET" in methods:
            methods.add("HEAD")
        ordered = [m for m in _METHOD_ORDER if m in methods] + sorted(
            methods.difference(_METHOD_ORDER)
        )
        return ", ".join(ordered)
