"""Routing, method dispatch, HEAD, middleware."""

from miniweb import Application
from conftest import request, start_server


def test_get_route(addr):
    status, _, body = request(addr, "GET", "/hello")
    assert status == 200 and body == b"hello"


def test_path_params(addr):
    status, _, body = request(addr, "GET", "/users/42")
    assert status == 200 and body == b"user:42"


def test_path_param_does_not_swallow_slashes(addr):
    status, _, _ = request(addr, "GET", "/users/1/2")
    assert status == 404


def test_unknown_path_404(addr):
    status, headers, body = request(addr, "GET", "/nope")
    assert status == 404
    assert b"404" in body


def test_method_not_allowed_405_with_allow(addr):
    status, headers, body = request(addr, "POST", "/hello")
    assert status == 405
    assert "GET" in headers["allow"]
    assert b"405" in body


def test_put_and_delete(addr):
    status, _, body = request(addr, "PUT", "/items/7")
    assert (status, body) == (200, b"put:7")
    status, _, body = request(addr, "DELETE", "/items/7")
    assert (status, body) == (200, b"delete:7")


def test_head_request(addr):
    status, headers, body = request(addr, "HEAD", "/hello")
    assert status == 200
    assert body == b""                       # no body on the wire
    assert int(headers["content-length"]) == 5  # ...but correct length


def test_redirects(addr):
    status, headers, _ = request(addr, "GET", "/old-page")
    assert status == 301 and headers["location"] == "/hello"
    status, headers, _ = request(addr, "GET", "/found")
    assert status == 302 and headers["location"] == "/hello"


def test_body_types():
    app = Application()

    @app.get("/str")
    def as_str(request):
        return 200, [], "text"

    @app.get("/bytes")
    def as_bytes(request):
        return 200, [], b"bytes"

    @app.get("/none")
    def as_none(request):
        return 204, [], None

    handle = start_server(app=app)
    try:
        assert request(handle.addr, "GET", "/str")[2] == b"text"
        assert request(handle.addr, "GET", "/bytes")[2] == b"bytes"
        status, headers, body = request(handle.addr, "GET", "/none")
        assert status == 204 and body == b""
        assert headers["content-length"] == "0"
    finally:
        handle.server.shutdown()


def test_middleware_hooks():
    app = Application()
    calls = []

    @app.before_request
    def auth(request):
        calls.append(("before", request.path))
        if request.path == "/blocked":
            return 403, [], "blocked by middleware"
        return None

    @app.after_response
    def add_header(request, response):
        calls.append(("after", request.path))
        status, headers, body = response
        return status, list(headers) + [("X-After", "yes")], body

    @app.get("/ok")
    def ok(request):
        return 200, [], "ok"

    handle = start_server(app=app)
    try:
        status, headers, body = request(handle.addr, "GET", "/ok")
        assert status == 200 and headers["x-after"] == "yes"
        status, _, body = request(handle.addr, "GET", "/blocked")
        assert status == 403 and body == b"blocked by middleware"
        assert ("before", "/ok") in calls and ("after", "/ok") in calls
    finally:
        handle.server.shutdown()
