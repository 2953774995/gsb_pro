"""Error status pages, 500 containment, 413, required headers."""

from miniweb import Application, HTTPServer
from conftest import make_request, raw_exchange


def test_404_default_error_page(port):
    resp, sock = make_request(port, "GET", "/missing")
    assert resp.status == 404
    assert b"404" in resp.body and b"Not Found" in resp.body
    assert resp.header("content-type").startswith("text/html")
    sock.close()


def test_405_default_error_page(port):
    resp, sock = make_request(port, "POST", "/hello")
    assert resp.status == 405
    assert b"405" in resp.body and b"Method Not Allowed" in resp.body
    sock.close()


def test_400_default_error_page(port):
    raw = raw_exchange(port, b"BADREQUEST\r\n\r\n")
    assert raw.startswith(b"HTTP/1.1 400")
    assert b"Bad Request" in raw


def test_handler_exception_becomes_500_without_leak(port):
    resp, sock = make_request(port, "GET", "/boom")
    assert resp.status == 500
    assert b"Internal Server Error" in resp.body
    assert b"secret internal failure" not in resp.body
    assert b"Traceback" not in resp.body
    sock.close()
    # Server still alive after the 500.
    resp, sock = make_request(port, "GET", "/hello")
    assert resp.status == 200
    sock.close()


def test_payload_too_large_413():
    app = Application()

    @app.post("/upload")
    def upload(request):
        return 200, {}, "ok"

    srv = HTTPServer(app, host="127.0.0.1", port=0, timeout=5,
                     max_body_bytes=16).start()
    try:
        resp, sock = make_request(srv.port, "POST", "/upload",
                                  body=b"x" * 100)
        assert resp.status == 413
        assert b"Payload Too Large" in resp.body
        sock.close()
    finally:
        srv.shutdown()


def test_required_response_headers(port):
    resp, sock = make_request(port, "GET", "/hello")
    for name in ("content-type", "content-length", "connection", "server", "date"):
        assert resp.header(name) is not None, "missing header %s" % name
    assert "miniweb" in resp.header("server")
    assert "GMT" in resp.header("date")
    sock.close()


def test_redirect_status_codes():
    app = Application()

    @app.get("/old")
    def old(request):
        return 301, {"Location": "/new"}, None

    @app.get("/temp")
    def temp(request):
        return 302, {"Location": "/elsewhere"}, None

    srv = HTTPServer(app, host="127.0.0.1", port=0, timeout=5).start()
    try:
        resp, sock = make_request(srv.port, "GET", "/old")
        assert resp.status == 301
        assert resp.header("location") == "/new"
        resp, _ = make_request(srv.port, "GET", "/temp", sock=sock)
        assert resp.status == 302
        assert resp.header("location") == "/elsewhere"
        sock.close()
    finally:
        srv.shutdown()


def test_malformed_requests_do_not_kill_server(port):
    for junk in (b"\x00\x01\x02\r\n\r\n",
                 b"GET\r\n\r\n",
                 b"GET / HTTP/1.1\r\nBad\r\n\r\n"):
        raw_exchange(port, junk)
    resp, sock = make_request(port, "GET", "/hello")
    assert resp.status == 200
    sock.close()
