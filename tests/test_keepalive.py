"""Keep-Alive semantics: HTTP/1.1 keeps connections open by default,
Connection: close and HTTP/1.0 close them."""

import socket
import time

from conftest import open_conn, read_response, request, start_server


def _get(path, connection=None, version="HTTP/1.1"):
    lines = ["GET %s %s" % (path, version), "Host: localhost"]
    if connection:
        lines.append("Connection: %s" % connection)
    return ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1")


def test_two_requests_one_connection(addr):
    sock, rfile = open_conn(addr)
    try:
        sock.sendall(_get("/hello"))
        status, headers, body = read_response(rfile)
        assert status == 200 and body == b"hello"
        assert headers["connection"] == "keep-alive"

        sock.sendall(_get("/users/9"))
        status, headers, body = read_response(rfile)
        assert status == 200 and body == b"user:9"
    finally:
        sock.close()


def test_many_requests_pipelined_sequentially(addr):
    sock, rfile = open_conn(addr)
    try:
        for i in range(5):
            sock.sendall(_get("/users/%d" % i))
            status, _, body = read_response(rfile)
            assert status == 200
            assert body == ("user:%d" % i).encode()
    finally:
        sock.close()


def test_connection_close_header(addr):
    sock, rfile = open_conn(addr)
    try:
        sock.sendall(_get("/hello", connection="close"))
        status, headers, body = read_response(rfile)
        assert status == 200 and body == b"hello"
        assert headers["connection"] == "close"
        # server must close: further reads return EOF
        assert rfile.read() == b""
    finally:
        sock.close()


def test_http10_defaults_to_close(addr):
    sock, rfile = open_conn(addr)
    try:
        sock.sendall(_get("/hello", version="HTTP/1.0"))
        status, headers, body = read_response(rfile)
        assert status == 200
        assert headers["connection"] == "close"
        assert rfile.read() == b""
    finally:
        sock.close()


def test_http10_explicit_keepalive(addr):
    sock, rfile = open_conn(addr)
    try:
        sock.sendall(_get("/hello", connection="keep-alive",
                          version="HTTP/1.0"))
        status, headers, body = read_response(rfile)
        assert status == 200 and headers["connection"] == "keep-alive"
        sock.sendall(_get("/hello", connection="close", version="HTTP/1.0"))
        status, headers, body = read_response(rfile)
        assert status == 200 and headers["connection"] == "close"
    finally:
        sock.close()


def test_idle_timeout_closes_connection():
    handle = start_server(idle_timeout=0.5)
    try:
        sock, rfile = open_conn(handle.addr)
        try:
            sock.sendall(_get("/hello"))
            status, _, _ = read_response(rfile)
            assert status == 200
            time.sleep(1.2)  # exceed the idle timeout
            assert rfile.read() == b""  # server closed the connection
        finally:
            sock.close()
    finally:
        handle.server.shutdown()


def test_post_then_get_on_same_connection(addr):
    sock, rfile = open_conn(addr)
    try:
        body = b"x=1"
        sock.sendall(
            b"POST /echo HTTP/1.1\r\nHost: x\r\nContent-Length: 3\r\n"
            b"Content-Type: application/octet-stream\r\n\r\n" + body)
        status, _, resp_body = read_response(rfile)
        assert status == 200 and resp_body == body
        sock.sendall(_get("/hello", connection="close"))
        status, _, resp_body = read_response(rfile)
        assert status == 200 and resp_body == b"hello"
    finally:
        sock.close()
