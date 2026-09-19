"""Error status codes, default error pages, exception containment."""

from conftest import raw_request, request


def test_404_default_page(addr):
    status, headers, body = request(addr, "GET", "/no-such-thing")
    assert status == 404
    assert b"404" in body and b"Not Found" in body
    assert "text/html" in headers["content-type"]
    assert int(headers["content-length"]) == len(body)


def test_405_default_page(addr):
    status, headers, body = request(addr, "DELETE", "/hello")
    assert status == 405
    assert b"405" in body
    assert "GET" in headers["allow"]


def test_400_default_page(addr):
    resp = raw_request(addr, b"GARBAGE REQUEST\r\n\r\n")
    assert resp.startswith(b"HTTP/1.1 400")
    assert b"400" in resp and b"Bad Request" in resp


def test_500_on_handler_exception(addr):
    status, headers, body = request(addr, "GET", "/boom")
    assert status == 500
    assert b"500" in body
    # no traceback / internals leaked to the client
    assert b"Traceback" not in body
    assert b"RuntimeError" not in body
    assert b"secret internal explosion" not in body


def test_server_survives_handler_exceptions(addr):
    for _ in range(3):
        status, _, _ = request(addr, "GET", "/boom")
        assert status == 500
    status, _, body = request(addr, "GET", "/hello")
    assert status == 200 and body == b"hello"


def test_required_response_headers(addr):
    _, headers, _ = request(addr, "GET", "/hello")
    for name in ("content-type", "content-length", "connection",
                 "server", "date"):
        assert name in headers, name
    assert headers["server"].startswith("miniweb")


def test_error_responses_have_required_headers(addr):
    _, headers, _ = request(addr, "GET", "/missing")
    for name in ("content-type", "content-length", "connection",
                 "server", "date"):
        assert name in headers, name


def test_head_on_error_page(addr):
    status, headers, body = request(addr, "HEAD", "/missing")
    assert status == 404
    assert body == b""
    assert int(headers["content-length"]) > 0
