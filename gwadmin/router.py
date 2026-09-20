"""URL router with path parameters and middleware hooks."""

from .http import HTTPError

_METHODS = ("GET", "POST", "PUT", "DELETE", "HEAD", "OPTIONS")


class Route(object):
    __slots__ = ("methods", "segments", "handler")

    def __init__(self, methods, segments, handler):
        self.methods = methods
        self.segments = segments
        self.handler = handler

    def match_path(self, path_segments):
        """Return path params dict if the path matches, else None."""
        if len(path_segments) != len(self.segments):
            return None
        params = {}
        for pattern, actual in zip(self.segments, path_segments):
            if pattern.startswith(":"):
                name = pattern[1:]
                if not name or actual == "":
                    return None
                params[name] = actual
            elif pattern != actual:
                return None
        return params


def _split(path):
    return [seg for seg in path.split("/") if seg != ""]


class Router(object):
    """Registers handlers and dispatches requests.

    Handler signature: handler(request) -> (status, headers, body)
    where body is bytes/str/None.
    """

    def __init__(self):
        self._routes = []
        self._before = []
        self._after = []

    # -- registration ----------------------------------------------------
    def add(self, methods, pattern, handler):
        if isinstance(methods, str):
            methods = [methods]
        methods = tuple(m.upper() for m in methods)
        for m in methods:
            if m not in _METHODS:
                raise ValueError("unsupported method: %r" % m)
        self._routes.append(Route(methods, _split(pattern), handler))
        return handler

    def route(self, pattern, methods=("GET",)):
        def decorator(func):
            self.add(methods, pattern, func)
            return func
        return decorator

    def get(self, pattern):
        return self.route(pattern, ("GET",))

    def post(self, pattern):
        return self.route(pattern, ("POST",))

    def put(self, pattern):
        return self.route(pattern, ("PUT",))

    def delete(self, pattern):
        return self.route(pattern, ("DELETE",))

    # -- middleware hooks --------------------------------------------------
    def before_request(self, func):
        """Hook: func(request) -> None, or a (status, headers, body)
        response tuple to short-circuit handling."""
        self._before.append(func)
        return func

    def after_request(self, func):
        """Hook: func(request, response_tuple) -> response_tuple."""
        self._after.append(func)
        return func

    # -- dispatch ----------------------------------------------------------
    def dispatch(self, request):
        """Return (status, headers, body). Raises nothing for 404/405."""
        path_segments = _split(request.path)
        allowed = []
        for route in self._routes:
            params = route.match_path(path_segments)
            if params is None:
                continue
            if request.method in route.methods or (
                    request.method == "HEAD" and "GET" in route.methods):
                request.path_params = params
                return self._run(request, route.handler)
            allowed.extend(route.methods)
        if allowed:
            allow = sorted(set(allowed) | {"HEAD"} if "GET" in allowed
                           else set(allowed))
            return 405, [("Allow", ", ".join(allow))], None
        return 404, [], None

    def _run(self, request, handler):
        for hook in self._before:
            result = hook(request)
            if result is not None:
                response = result
                break
        else:
            response = handler(request)
        status, headers, body = _normalize(response)
        for hook in self._after:
            status, headers, body = _normalize(
                hook(request, (status, headers, body)))
        return status, headers, body


def _normalize(response):
    if not isinstance(response, tuple) or len(response) != 3:
        raise HTTPError(500, "handler returned an invalid response")
    status, headers, body = response
    if headers is None:
        headers = []
    return int(status), list(headers), body
