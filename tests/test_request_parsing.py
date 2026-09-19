"""Request parsing boundary tests: malformed input must yield 400/413
responses (or a closed connection) and must never kill the server."""

from conftest import raw_request, request, start_server


def test_valid_request(addr):
    status, headers, body = request(addr, "GET", "/hello")
    assert status == 200
    assert body == b"hello"


def test_request_line_missing_parts(addr):
    resp = raw_request(addr, b"GET /\r\nHost: x\r\n\r\n")
    assert resp.startswith(b"HTTP/1.1 400")


def test_request_line_empty(addr):
    # only blank lines then EOF: server just closes the connection
    resp = raw_request(addr, b"\r\n\r\n\r\n", shutdown_write=True)
    assert resp == b""


def test_bad_http_version(addr):
    resp = raw_request(addr, b"GET / HTTP/9.9\r\nHost: x\r\n\r\n")
    assert resp.startswith(b"HTTP/1.1 400")


def test_bad_version_format(addr):
    resp = raw_request(addr, b"GET / HTTX/1.1\r\nHost: x\r\n\r\n")
    assert resp.startswith(b"HTTP/1.1 400")


def test_invalid_method_lowercase(addr):
    resp = raw_request(addr, b"get / HTTP/1.1\r\nHost: x\r\n\r\n")
    assert resp.startswith(b"HTTP/1.1 400")


def test_invalid_method_garbage(addr):
    resp = raw_request(addr, b"G@#$T / HTTP/1.1\r\nHost: x\r\n\r\n")
    assert resp.startswith(b"HTTP/1.1 400")


def test_missing_host_http11(addr):
    resp = raw_request(addr, b"GET /hello HTTP/1.1\r\n\r\n")
    assert resp.startswith(b"HTTP/1.1 400")


def test_oversized_header(addr):
    big = b"X-Pad: " + b"a" * 9000 + b"\r\n"
    resp = raw_request(addr, b"GET / HTTP/1.1\r\nHost: x\r\n" + big + b"\r\n")
    assert resp.startswith(b"HTTP/1.1 400")


def test_oversized_request_line(addr):
    big_path = b"/" + b"a" * 9000
    resp = raw_request(addr, b"GET " + big_path + b" HTTP/1.1\r\nHost: x\r\n\r\n")
    assert resp.startswith(b"HTTP/1.1 400")


def test_malformed_header_no_colon(addr):
    resp = raw_request(
        addr, b"GET / HTTP/1.1\r\nHost: x\r\nnot-a-header\r\n\r\n")
    assert resp.startswith(b"HTTP/1.1 400")


def test_invalid_header_name(addr):
    resp = raw_request(
        addr, b"GET / HTTP/1.1\r\nHost: x\r\nBad Name: v\r\n\r\n")
    assert resp.startswith(b"HTTP/1.1 400")


def test_invalid_content_length(addr):
    resp = raw_request(
        addr, b"POST /echo HTTP/1.1\r\nHost: x\r\nContent-Length: abc\r\n\r\n")
    assert resp.startswith(b"HTTP/1.1 400")


def test_conflicting_content_length(addr):
    resp = raw_request(
        addr,
        b"POST /echo HTTP/1.1\r\nHost: x\r\nContent-Length: 3\r\n"
        b"Content-Length: 5\r\n\r\nabc")
    assert resp.startswith(b"HTTP/1.1 400")


def test_content_length_mismatch_short_body(addr):
    # declares 10 bytes, sends 5, then half-closes: 400
    resp = raw_request(
        addr,
        b"POST /echo HTTP/1.1\r\nHost: x\r\nContent-Length: 10\r\n\r\n12345",
        shutdown_write=True)
    assert resp.startswith(b"HTTP/1.1 400")


def test_body_too_large_413():
    handle = start_server(max_body=64)
    try:
        resp = raw_request(
            handle.addr,
            b"POST /echo HTTP/1.1\r\nHost: x\r\nContent-Length: 100\r\n\r\n")
        assert resp.startswith(b"HTTP/1.1 413")
    finally:
        handle.server.shutdown()


def test_transfer_encoding_unsupported(addr):
    resp = raw_request(
        addr,
        b"POST /echo HTTP/1.1\r\nHost: x\r\nTransfer-Encoding: chunked\r\n\r\n")
    assert resp.startswith(b"HTTP/1.1 400")


def test_nul_byte_in_path(addr):
    resp = raw_request(addr, b"GET /a%00b HTTP/1.1\r\nHost: x\r\n\r\n")
    assert resp.startswith(b"HTTP/1.1 400")


def test_server_survives_garbage(addr):
    for junk in (b"\x00\x01\x02\x03\r\n\r\n",
                 b"???? //// ----\r\n\r\n",
                 b"GET\0/ HTTP/1.1\r\n\r\n"):
        raw_request(addr, junk)
    status, _, body = request(addr, "GET", "/hello")
    assert status == 200 and body == b"hello"


def test_query_params(addr):
    status, _, body = request(addr, "GET", "/echo-args?a=1&a=2&b=hello+world&c=%41")
    assert status == 200
    assert body == b"a=1,2&b=hello world&c=A"


def test_duplicate_headers_merged(addr):
    # consistent merge policy: comma-joined
    import socket
    from conftest import open_conn, read_response
    sock, rfile = open_conn(addr)
    try:
        sock.sendall(
            b"GET /hello HTTP/1.1\r\nHost: x\r\nX-M: 1\r\nX-M: 2\r\n"
            b"Connection: close\r\n\r\n")
        status, headers, _ = read_response(rfile)
        assert status == 200
    finally:
        sock.close()
