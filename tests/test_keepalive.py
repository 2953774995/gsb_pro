"""Keep-alive, connection reuse, HTTP/1.0 semantics, idle timeout."""

import socket
import time

from miniweb import Application, HTTPServer
from conftest import make_request, read_response


def test_two_requests_same_connection(port):
    sock = socket.create_connection(("127.0.0.1", port), timeout=5)
    resp1, _ = make_request(port, "GET", "/hello", sock=sock)
    assert resp1.status == 200
    assert resp1.header("connection") == "keep-alive"
    resp2, _ = make_request(port, "GET", "/users/7", sock=sock)
    assert resp2.status == 200
    assert resp2.body == b"user:7"
    sock.close()


def test_connection_close_header_honored(port):
    sock = socket.create_connection(("127.0.0.1", port), timeout=5)
    resp, _ = make_request(port, "GET", "/hello",
                           headers={"Connection": "close"}, sock=sock)
    assert resp.status == 200
    assert resp.header("connection") == "close"
    # Server must close the connection after the response.
    assert sock.recv(1) == b""
    sock.close()


def test_http10_defaults_to_close(port):
    sock = socket.create_connection(("127.0.0.1", port), timeout=5)
    resp, _ = make_request(port, "GET", "/hello", version="HTTP/1.0", sock=sock)
    assert resp.status == 200
    assert resp.header("connection") == "close"
    assert sock.recv(1) == b""
    sock.close()


def test_http10_keep_alive_opt_in(port):
    sock = socket.create_connection(("127.0.0.1", port), timeout=5)
    resp1, _ = make_request(port, "GET", "/hello", version="HTTP/1.0",
                            headers={"Connection": "keep-alive"}, sock=sock)
    assert resp1.status == 200
    assert resp1.header("connection") == "keep-alive"
    resp2, _ = make_request(port, "GET", "/hello", version="HTTP/1.0",
                            headers={"Connection": "close"}, sock=sock)
    assert resp2.status == 200
    sock.close()


def test_pipelined_requests(port):
    sock = socket.create_connection(("127.0.0.1", port), timeout=5)
    req = b"GET /hello HTTP/1.1\r\nHost: x\r\n\r\n"
    sock.sendall(req + req)
    r1 = read_response(sock)
    r2 = read_response(sock)
    assert r1.status == 200 and r2.status == 200
    sock.close()


def test_idle_connection_times_out():
    app = Application()

    @app.get("/hello")
    def hello(request):
        return 200, {}, "hi"

    srv = HTTPServer(app, host="127.0.0.1", port=0, timeout=0.3).start()
    try:
        sock = socket.create_connection(("127.0.0.1", srv.port), timeout=5)
        resp, _ = make_request(srv.port, "GET", "/hello", sock=sock)
        assert resp.status == 200
        deadline = time.time() + 3
        closed = False
        while time.time() < deadline:
            try:
                if sock.recv(1) == b"":
                    closed = True
                    break
            except socket.timeout:
                continue
        assert closed, "server did not close idle connection"
        sock.close()
    finally:
        srv.shutdown()
