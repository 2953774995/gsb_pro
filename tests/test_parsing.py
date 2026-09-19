"""Request parsing boundary tests against a real TCP server."""

import pytest


def test_basic_request_and_query(client):
    resp = client.request("GET", "/hello?name=alice")
    assert resp.status == 200
    assert resp.body == b"hi alice"
    assert "date" in resp.headers
    assert resp.headers["server"].startswith("miniweb")


def test_query_repeated_keys(client):
    resp = client.request("GET", "/hello?name=a&name=b")
    assert resp.status == 200
    assert resp.body == b"hi a"  # first value via .get


def test_malformed_request_line(client):
    resp = client.raw(b"GETALLGARBAGE\r\n\r\n")
    assert resp.status == 400
    assert resp.headers.get("connection") == "close"


def test_bad_method(client):
    resp = client.raw(b"WHATEVS / HTTP/1.1\r\nHost: x\r\n\r\n")
    assert resp.status == 400


def test_bad_version(client):
    resp = client.raw(b"GET / HTTP/9.9\r\nHost: x\r\n\r\n")
    assert resp.status == 400
    assert resp.headers.get("connection") == "close"
    # The connection must have been torn down: next read gives EOF.
    client.fp.close()
    assert client.sock.recv(16) == b""


def test_http_1_0_allowed_with_host(client, server, make_client):
    resp = client.request("GET", "/hello", version="HTTP/1.0")
    assert resp.status == 200
    # HTTP/1.0 without keep-alive closes by default.
    assert resp.headers.get("connection") == "close"


def test_missing_host_1_1(server, make_client):
    client = make_client(server)
    resp = client.raw(b"GET /hello HTTP/1.1\r\n\r\n")
    assert resp.status == 400


def test_duplicate_host_400(client):
    resp = client.raw(
        b"GET /hello HTTP/1.1\r\nHost: a\r\nHost: b\r\n\r\n"
    )
    assert resp.status == 400


def test_malformed_header_line(client):
    resp = client.raw(
        b"GET /hello HTTP/1.1\r\nHost: x\r\nBogus-Header\r\n\r\n"
    )
    assert resp.status == 400


def test_non_ascii_header_name(client):
    resp = client.raw(
        b"GET /hello HTTP/1.1\r\nHost: x\r\nX\xff: 1\r\n\r\n"
    )
    assert resp.status == 400


def test_header_too_long_returns_400(server, make_client):
    client = make_client(server)
    huge = b"X-Big: " + b"a" * (9000)
    resp = client.raw(b"GET /hello HTTP/1.1\r\nHost: x\r\n" + huge + b"\r\n\r\n")
    assert resp.status == 400


def test_request_line_too_long_returns_400(server, make_client):
    client = make_client(server)
    target = b"/" + b"a" * 9000
    resp = client.raw(
        b"GET " + target + b" HTTP/1.1\r\nHost: x\r\n\r\n"
    )
    assert resp.status == 400


def test_content_length_mismatch_server_does_not_hang(
    server_factory, make_client
):
    from miniweb import Config

    cfg = Config(host="127.0.0.1", port=0, timeout=1.0)
    srv = server_factory(config=cfg)
    # Claims 100 bytes but sends only 5 then keeps the socket open.
    client = make_client(srv, timeout=5.0)
    client.sock.sendall(
        b"POST /echo HTTP/1.1\r\n"
        b"Host: x\r\n"
        b"Content-Length: 100\r\n"
        b"Content-Type: application/x-www-form-urlencoded\r\n\r\n"
        b"hello"
    )
    # The server must not wait forever: idle timeout fires (1s) and the
    # connection is closed (no response can be framed for an unread body).
    client.fp.close()
    assert client.sock.recv(16) == b""


def test_invalid_content_length_non_numeric(client):
    resp = client.raw(
        b"POST /echo HTTP/1.1\r\n"
        b"Host: x\r\nContent-Length: ten\r\n\r\n"
    )
    assert resp.status == 400


def test_duplicate_content_length_400(client):
    resp = client.raw(
        b"POST /echo HTTP/1.1\r\n"
        b"Host: x\r\nContent-Length: 0\r\nContent-Length: 1\r\n\r\n"
    )
    assert resp.status == 400


def test_body_too_large_returns_413(server_factory, make_client):
    from miniweb import Config

    cfg = Config(host="127.0.0.1", port=0, max_body_size=16)
    srv = server_factory(config=cfg)
    client = make_client(srv)
    resp = client.request(
        "POST",
        "/echo",
        headers=[("Content-Type", "text/plain")],
        body=b"x" * 32,
    )
    assert resp.status == 413


def test_server_survives_garbage_then_valid_request(client, server, make_client):
    resp = client.raw(b"\x00\x01\x02 not http at all\r\n\r\n")
    assert resp.status == 400
    # Fresh connection still serves traffic.
    fresh = make_client(server)
    resp = fresh.request("GET", "/hello")
    assert resp.status == 200
    assert resp.body == b"hi world"


def test_header_case_insensitive(client):
    resp = client.raw(
        b"GET /hello HTTP/1.1\r\nHoSt: x\r\nX-TEST: 1\r\n\r\n"
    )
    assert resp.status == 200


def test_duplicate_normal_headers_merged(client):
    # Two X-Test headers must not break parsing; route still works.
    resp = client.raw(
        b"GET /hello HTTP/1.1\r\nHost: x\r\nX-Test: a\r\nX-Test: b\r\n\r\n"
    )
    assert resp.status == 200
