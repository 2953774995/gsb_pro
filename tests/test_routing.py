"""Routing, method dispatch, path params, middleware hooks."""

from miniweb import Application, HTTPServer
from conftest import make_request


def test_get_route(port):
    resp, sock = make_request(port, "GET", "/hello")
    assert resp.status == 200
    assert resp.body == b"hello"
    sock.close()


def test_path_param_route(port):
    resp, sock = make_request(port, "GET", "/users/42")
    assert resp.status == 200
    assert resp.body == b"user:42"
    sock.close()


def test_unregistered_path_404(port):
    resp, sock = make_request(port, "GET", "/missing")
    assert resp.status == 404
    assert b"404" in resp.body
    sock.close()


def test_method_not_allowed_405_with_allow(port):
    resp, sock = make_request(port, "POST", "/hello")
    assert resp.status == 405
    allow = resp.header("allow")
    assert allow is not None
    assert "GET" in allow
    sock.close()


def test_put_and_delete_routes(port):
    resp, sock = make_request(port, "PUT", "/item")
    assert resp.status == 200 and resp.body == b"put"
    resp, _ = make_request(port, "DELETE", "/item", sock=sock)
    assert resp.status == 200 and resp.body == b"deleted"
    sock.close()


def test_handler_returning_none_body(port):
    app = Application()

    @app.get("/empty")
    def empty(request):
        return 204, {}, None

    srv = HTTPServer(app, host="127.0.0.1", port=0, timeout=5).start()
    try:
        resp, sock = make_request(srv.port, "GET", "/empty")
        assert resp.status == 204
        assert resp.header("content-length") == "0"
        sock.close()
    finally:
        srv.shutdown()


def test_middleware_hooks():
    app = Application()
    calls = []

    @app.get("/x")
    def x(request):
        return 200, {}, "x"

    def before(request):
        calls.append(("before", request.path))
        if request.path == "/blocked":
            return 403, {}, "blocked by middleware"
        return None

    def after(request, response):
        calls.append(("after", request.path))
        response.headers["X-After"] = "yes"
        return response

    app.before_request.append(before)
    app.after_response.append(after)

    srv = HTTPServer(app, host="127.0.0.1", port=0, timeout=5).start()
    try:
        resp, sock = make_request(srv.port, "GET", "/x")
        assert resp.status == 200
        assert resp.header("x-after") == "yes"
        resp, _ = make_request(srv.port, "GET", "/blocked", sock=sock)
        assert resp.status == 403
        assert resp.body == b"blocked by middleware"
        sock.close()
    finally:
        srv.shutdown()
    assert ("before", "/x") in calls
    assert ("after", "/x") in calls
