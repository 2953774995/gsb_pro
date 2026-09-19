"""Pure unit tests: router, static resolution, response normalization."""

import os

import pytest

from miniweb import HTTPError, Response
from miniweb.response import error_response, normalize, serialize
from miniweb.router import Router
from miniweb.static import guess_mime, serve_static


def test_router_basic_match():
    router = Router()
    router.add("GET", "/foo", lambda req: "ok")
    handler, params = router.match("GET", "/foo")
    assert params == {}
    assert handler(None) == "ok"


def test_router_params():
    router = Router()
    router.add("GET", "/users/:id/posts/:pid", lambda req: None)
    _, params = router.match("GET", "/users/42/posts/9")
    assert params == {"id": "42", "pid": "9"}


def test_router_no_match_404():
    router = Router()
    router.add("GET", "/foo", lambda req: None)
    with pytest.raises(HTTPError) as exc:
        router.match("GET", "/bar")
    assert exc.value.status == 404


def test_router_405_allow():
    router = Router()
    router.add("GET", "/foo", lambda req: None)
    router.add("POST", "/foo", lambda req: None)
    with pytest.raises(HTTPError) as exc:
        router.match("DELETE", "/foo")
    assert exc.value.status == 405
    allowed = exc.value.headers["Allow"]
    assert "GET" in allowed and "POST" in allowed and "DELETE" not in allowed


def test_router_head_falls_back_to_get():
    router = Router()
    router.add("GET", "/foo", lambda req: None)
    handler, _ = router.match("HEAD", "/foo")
    assert callable(handler)


def test_router_decorators():
    router = Router()

    @router.post("/items")
    def create(req):
        return None

    handler, _ = router.match("POST", "/items")
    assert handler is create


def test_router_params_dont_cross_segments():
    router = Router()
    router.add("GET", "/users/:id", lambda req: None)
    with pytest.raises(HTTPError):
        router.match("GET", "/users/1/2")


def test_guess_mime():
    assert guess_mime("a.html") == "text/html; charset=utf-8"
    assert guess_mime("a.PNG") == "image/png"
    assert guess_mime("a.unknown") == "application/octet-stream"


def test_normalize_tuple_forms():
    resp = normalize((201, None, b"data"))
    assert resp.status == 201 and resp.body == b"data"
    resp = normalize("hello")
    assert resp.status == 200 and resp.body == b"hello"
    resp = normalize(("solo",))
    assert resp.status == 200 and resp.body == b"solo"
    resp = normalize((200, [("X", "y")], "text"))
    assert resp.get_header("X") == "y"
    assert resp.body == b"text"


def test_normalize_str_gets_html_content_type():
    resp = normalize((200, None, "<p>x</p>"))
    assert resp.get_header("Content-Type") == "text/html; charset=utf-8"


def test_normalize_invalid_body_type():
    with pytest.raises(TypeError):
        normalize((200, None, 123))


def test_serialize_headers_and_head():
    resp = Response(200, [("Content-Type", "text/plain")], b"abc")
    data = serialize(resp, "HTTP/1.1", keep_alive=True, include_body=False)
    assert data.startswith(b"HTTP/1.1 200 OK\r\n")
    assert data.endswith(b"\r\n\r\n")
    assert b"Content-Length: 3" in data
    assert b"Server: miniweb" in data
    assert b"Connection: keep-alive" in data
    assert b"Date:" in data
    full = serialize(resp, "HTTP/1.1", keep_alive=False)
    assert full.endswith(b"abc")
    assert b"Connection: close" in full


def test_error_response_page():
    resp = error_response(404)
    assert resp.status == 404
    assert b"404" in resp.body
    assert resp.get_header("Content-Length") == str(len(resp.body))


STATIC_ROOT = os.path.join(os.path.dirname(__file__), "static")


def test_serve_static_file():
    resp = serve_static(STATIC_ROOT, "/style.css")
    assert resp.status == 200
    assert "text/css" in resp.get_header("Content-Type")
    assert b"color" in resp.body


def test_serve_static_traversal():
    with pytest.raises(HTTPError) as exc:
        serve_static(STATIC_ROOT, "/../etc/passwd")
    assert exc.value.status == 404
    with pytest.raises(HTTPError):
        serve_static(STATIC_ROOT, "/%2e%2e/etc/passwd")


def test_serve_static_missing():
    with pytest.raises(HTTPError) as exc:
        serve_static(STATIC_ROOT, "/nope.txt")
    assert exc.value.status == 404


def test_serve_static_directory_no_index():
    with pytest.raises(HTTPError) as exc:
        serve_static(STATIC_ROOT, "/noindex/")
    assert exc.value.status == 403
