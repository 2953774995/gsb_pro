"""Transport tests over socketpair (same handler path as real TCP)."""

import threading

import pytest

from conftest import PairClient, build_app


@pytest.fixture
def app():
    return build_app()


def test_pair_two_keepalive_requests(app):
    pair = PairClient(app)
    try:
        first = pair.request("GET", "/hello?name=one")
        assert first.status == 200
        assert first.body == b"hi one"
        assert first.headers["connection"] == "keep-alive"
        second = pair.request("GET", "/users/77")
        assert second.status == 200
        assert second.json() == {"id": "77"}
    finally:
        pair.close()


def test_pair_head_content_length(app):
    pair = PairClient(app)
    try:
        resp = pair.request("HEAD", "/hello")
        assert resp.status == 200
        assert resp.body == b""
        assert int(resp.headers["content-length"]) == len(b"hi world")
    finally:
        pair.close()


def test_pair_post_form_then_get(app):
    pair = PairClient(app)
    try:
        resp = pair.request(
            "POST",
            "/echo",
            headers=[
                ("Content-Type", "application/x-www-form-urlencoded")
            ],
            body=b"name=a&tag=1&tag=2",
        )
        assert resp.status == 200
        assert resp.json() == {"name": "a", "tag": ["1", "2"]}
        second = pair.request("GET", "/hello")
        assert second.status == 200
    finally:
        pair.close()


def test_pair_bad_request_then_connection_closed(app):
    pair = PairClient(app)
    try:
        resp = pair.raw(b"GARBAGE NOT HTTP\r\n\r\n")
        assert resp.status == 400
        assert resp.headers["connection"] == "close"
        pair.fp.close()
        assert pair.sock.recv(16) == b""
        pair.join(5)
        assert not pair.thread.is_alive()
    finally:
        pair.close()


def test_pair_huge_header_400(app):
    pair = PairClient(app)
    try:
        resp = pair.raw(
            b"GET /hello HTTP/1.1\r\nHost: x\r\nX-Big: "
            + b"a" * 9000
            + b"\r\n\r\n"
        )
        assert resp.status == 400
    finally:
        pair.close()


def test_pair_missing_host_400(app):
    pair = PairClient(app)
    try:
        resp = pair.raw(b"GET /hello HTTP/1.1\r\n\r\n")
        assert resp.status == 400
    finally:
        pair.close()


def test_pair_traversal_404(app):
    pair = PairClient(app)
    try:
        for evil in (
            "/../etc/passwd",
            "/%2e%2e/etc/passwd",
            "/sub/..%2f..%2fetc/passwd",
        ):
            resp = pair.request("GET", evil)
            assert resp.status == 404
            assert b"root:" not in resp.body
    finally:
        pair.close()


def test_pair_static_index(app):
    pair = PairClient(app)
    try:
        resp = pair.request("GET", "/index.html")
        assert resp.status == 200
        assert "text/html" in resp.headers["content-type"]
        assert b"Hello from miniweb" in resp.body
    finally:
        pair.close()


def test_pair_500_safe(app):
    pair = PairClient(app)
    try:
        resp = pair.request("GET", "/boom")
        assert resp.status == 500
        assert b"Traceback" not in resp.body
        # keep-alive continues after a 500 (response was fully framed)
        second = pair.request("GET", "/hello")
        assert second.status == 200
    finally:
        pair.close()


def test_pair_405_allow(app):
    pair = PairClient(app)
    try:
        resp = pair.request("POST", "/hello")
        assert resp.status == 405
        assert "GET" in resp.headers["allow"]
    finally:
        pair.close()


def test_pair_concurrent_isolated(app):
    count = 12
    errors = []
    barrier = threading.Barrier(count)

    def worker(index):
        pair = None
        try:
            pair = PairClient(app)
            barrier.wait(timeout=10)
            for _ in range(3):
                resp = pair.request("GET", "/echo/c%d" % index)
                assert resp.body == ("token=c%d" % index).encode()
        except Exception as exc:  # pragma: no cover
            errors.append(exc)
        finally:
            if pair is not None:
                pair.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert errors == []
    assert all(not t.is_alive() for t in threads)


def test_pair_connection_close(app):
    pair = PairClient(app)
    try:
        resp = pair.request(
            "GET", "/hello", headers=[("Connection", "close")]
        )
        assert resp.headers["connection"] == "close"
        # Server side must close the socket; read via a fresh fd so that
        # buffered file object state does not mask the EOF.
        pair.fp.close()
        assert pair.sock.recv(16) == b""
        pair.join(5)
        assert not pair.thread.is_alive()
    finally:
        pair.close()


def test_pair_chunked_body(app):
    body = (
        b"POST /echo HTTP/1.1\r\nHost: x\r\n"
        b"Content-Type: application/x-www-form-urlencoded\r\n"
        b"Transfer-Encoding: chunked\r\n\r\n"
        b"4\r\nname\r\n1\r\n=\r\n3\r\nabc\r\n0\r\n\r\n"
    )
    pair = PairClient(app)
    try:
        resp = pair.raw(body)
        assert resp.status == 200
        assert resp.json() == {"name": "abc"}
    finally:
        pair.close()
