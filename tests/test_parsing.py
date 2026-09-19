"""Request-line / header / body parsing edge cases."""

from conftest import make_request, raw_exchange


def test_valid_request(port):
    resp, sock = make_request(port, "GET", "/hello")
    assert resp.status == 200
    assert resp.body == b"hello"
    sock.close()


def test_garbage_request_line(port):
    raw = raw_exchange(port, b"GARBAGE\r\n\r\n")
    assert raw.startswith(b"HTTP/1.1 400")


def test_too_many_parts_in_request_line(port):
    raw = raw_exchange(port, b"GET / HTTP/1.1 EXTRA\r\nHost: x\r\n\r\n")
    assert raw.startswith(b"HTTP/1.1 400")


def test_invalid_method_characters(port):
    raw = raw_exchange(port, b"GE@T /hello HTTP/1.1\r\nHost: x\r\n\r\n")
    assert raw.startswith(b"HTTP/1.1 400")


def test_lowercase_method_rejected(port):
    raw = raw_exchange(port, b"get /hello HTTP/1.1\r\nHost: x\r\n\r\n")
    assert raw.startswith(b"HTTP/1.1 400")


def test_bad_http_version(port):
    raw = raw_exchange(port, b"GET /hello HTTP/9.9\r\nHost: x\r\n\r\n")
    assert raw.startswith(b"HTTP/1.1 400")


def test_malformed_version_token(port):
    raw = raw_exchange(port, b"GET /hello HTTX/1.1\r\nHost: x\r\n\r\n")
    assert raw.startswith(b"HTTP/1.1 400")


def test_missing_host_header(port):
    raw = raw_exchange(port, b"GET /hello HTTP/1.1\r\n\r\n")
    assert raw.startswith(b"HTTP/1.1 400")


def test_oversized_headers(port):
    big = b"X-Pad: " + b"a" * 9000 + b"\r\n"
    raw = raw_exchange(port, b"GET /hello HTTP/1.1\r\nHost: x\r\n" + big + b"\r\n")
    assert raw.startswith(b"HTTP/1.1 400")


def test_header_line_without_colon(port):
    raw = raw_exchange(port, b"GET /hello HTTP/1.1\r\nHost: x\r\nBadHeaderLine\r\n\r\n")
    assert raw.startswith(b"HTTP/1.1 400")


def test_invalid_header_name(port):
    raw = raw_exchange(port, b"GET /hello HTTP/1.1\r\nHost: x\r\nBad Name: v\r\n\r\n")
    assert raw.startswith(b"HTTP/1.1 400")


def test_invalid_content_length(port):
    raw = raw_exchange(port, b"POST /submit HTTP/1.1\r\nHost: x\r\nContent-Length: abc\r\n\r\n")
    assert raw.startswith(b"HTTP/1.1 400")


def test_content_length_mismatch(port):
    # Declares 10 bytes, sends 5, then half-closes: server must answer 400.
    raw = raw_exchange(
        port,
        b"POST /submit HTTP/1.1\r\nHost: x\r\nContent-Length: 10\r\n\r\nhello",
        shutdown_write=True,
    )
    assert raw.startswith(b"HTTP/1.1 400")


def test_nonexistent_path_is_404_not_crash(port):
    resp, sock = make_request(port, "GET", "/nope")
    assert resp.status == 404
    sock.close()


def test_query_string_parsing(app):
    @app.get("/q")
    def q(request):
        query = request.query
        return 200, {}, repr(sorted((k, tuple(v)) for k, v in query.items()))

    from miniweb import HTTPServer
    srv = HTTPServer(app, host="127.0.0.1", port=0, timeout=5).start()
    try:
        resp, sock = make_request(srv.port, "GET", "/q?a=1&a=2&b=x+y&c=")
        assert resp.status == 200
        assert b"('a', ('1', '2'))" in resp.body
        assert b"('b', ('x y',))" in resp.body
        assert b"('c', ('',))" in resp.body
        sock.close()
    finally:
        srv.shutdown()


def test_header_names_case_insensitive(port):
    resp, sock = make_request(port, "GET", "/hello",
                              headers={"hOsT": "127.0.0.1", "X-Custom": "v"})
    # Host was sent with weird casing and accepted (no 400).
    assert resp.status == 200
    sock.close()
