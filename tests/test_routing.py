import json

from helpers import http_request, parse_response, raw_request


def test_get_route_with_required_headers(port):
    status, headers, body, reason, version = http_request(
        port, "GET", "/hello?name=Ada", b"", {"Host": "example.com"}
    )
    assert status == 200
    assert reason == "OK"
    assert body == b"hello"
    assert headers["x-query"] == "Ada"
    assert headers["content-length"] == "5"
    assert headers["content-type"].startswith("text/plain")
    assert headers["connection"] == "keep-alive"
    assert headers["server"]
    assert headers["date"]
    assert version == "HTTP/1.1"


def test_path_parameter_and_query_aggregation(port):
    status, headers, body, *_ = http_request(
        port, "GET", "/users/7?tag=a&tag=b", b"", {"Host": "x"}
    )
    assert status == 200
    data = json.loads(body)
    assert data == {"id": "7", "q": {"tag": ["a", "b"]}}


def test_put_and_delete_routes(port):
    status, headers, body, *_ = http_request(
        port, "PUT", "/users/9", b"abc", {"Content-Type": "text/plain"}
    )
    assert status == 200
    assert body == b"updated 9"

    status, headers, body, *_ = http_request(
        port, "DELETE", "/users/9", b"", {"Host": "x"}
    )
    assert status == 204
    assert headers["content-length"] == "0"
    assert body == b""


def test_unregistered_path_404(port):
    status, headers, body, *_ = http_request(port, "GET", "/missing", b"")
    assert status == 404
    assert headers["content-type"] == "text/html; charset=utf-8"
    assert b"404 Not Found" in body


def test_method_mismatch_has_allow_header(port):
    status, headers, body, *_ = http_request(port, "DELETE", "/hello", b"")
    assert status == 405
    assert "GET" in headers["allow"]
    assert "HEAD" in headers["allow"]
    assert b"405 Method Not Allowed" in body


def test_head_route_headers_only_but_content_length_correct(port):
    status, headers, body, *_ = http_request(port, "HEAD", "/hello", b"")
    assert status == 200
    assert headers["content-length"] == "5"
    assert body == b""


def test_head_unknown_path_returns_error_headers_only(port):
    status, headers, body, *_ = http_request(port, "HEAD", "/missing", b"")
    assert status == 404
    assert int(headers["content-length"]) > 0
    assert body == b""


def test_redirects(port):
    status, headers, body, *_ = http_request(port, "GET", "/old", b"")
    assert status == 301
    assert headers["location"] == "/new"
    assert b"Redirecting" in body

    status, headers, body, *_ = http_request(port, "GET", "/short", b"")
    assert status == 302
    assert headers["location"] == "/hello"


def test_case_insensitive_and_duplicate_headers(port):
    payload = (
        b"POST /form HTTP/1.1\r\n"
        b"HOST: localhost\r\n"
        b"content-TYPE: application/x-www-form-urlencoded\r\n"
        b"X-Forwarded-For: 1.1.1.1\r\n"
        b"X-Forwarded-For: 2.2.2.2\r\n"
        b"Content-Length: 7\r\n\r\na=1&b=2"
    )
    status, headers, body, *_ = parse_response(raw_request(port, payload))
    assert status == 200
    assert json.loads(body) == {"a": "1", "b": "2"}


def test_middleware_hooks_are_observable(port):
    status, headers, body, *_ = http_request(port, "GET", "/middleware", b"")
    assert status == 200
    assert headers["x-after"] == "yes"
    assert body == b"base"

    # Middleware can replace a response through its return value.
    status, headers, body, *_ = http_request(port, "GET", "/middleware?change=1", b"")
    assert status == 201
    assert headers["x-middleware"] == "short-circuited"
    assert body == b"changed"
