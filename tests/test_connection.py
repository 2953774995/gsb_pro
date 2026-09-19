"""Keep-alive reuse, concurrent connections and shutdown behavior."""

import threading

from miniweb import Config


def test_keepalive_two_requests_one_connection(client):
    first = client.request("GET", "/hello?name=one")
    assert first.status == 200
    assert first.headers["connection"] == "keep-alive"
    assert first.body == b"hi one"

    second = client.request("GET", "/users/77")
    assert second.status == 200
    assert second.headers["connection"] == "keep-alive"
    assert second.json() == {"id": "77"}


def test_keepalive_post_then_get(client):
    post = client.request(
        "POST",
        "/echo",
        headers=[("Content-Type", "application/x-www-form-urlencoded")],
        body=b"x=1",
    )
    assert post.status == 200
    second = client.request("GET", "/hello")
    assert second.status == 200
    assert second.body == b"hi world"


def test_connection_close_header_tears_connection(client):
    resp = client.request(
        "GET", "/hello", headers=[("Connection", "close")]
    )
    assert resp.headers["connection"] == "close"
    leftover = client.fp.read()
    assert leftover == b""


def test_http10_keepalive_explicit(server, make_client):
    client = make_client(server)
    resp = client.raw(
        b"GET /hello HTTP/1.0\r\nHost: x\r\nConnection: keep-alive\r\n\r\n"
    )
    assert resp.status == 200
    assert resp.headers["connection"] == "keep-alive"
    second = client.raw(
        b"GET /hello HTTP/1.0\r\nHost: x\r\nConnection: keep-alive\r\n\r\n"
    )
    assert second.status == 200


def test_many_requests_on_one_connection(client):
    for index in range(20):
        resp = client.request("GET", "/echo/%d" % index)
        assert resp.status == 200
        assert resp.body == ("token=%d" % index).encode()


def test_concurrent_connections_no_cross_talk(server_factory, make_client):
    cfg = Config(host="127.0.0.1", port=0, workers=16)
    srv = server_factory(config=cfg)

    count = 12
    errors = []
    barrier = threading.Barrier(count)

    def worker(index):
        try:
            client = make_client(srv)
            barrier.wait(timeout=10)
            for _ in range(3):
                resp = client.request("GET", "/echo/client-%d" % index)
                assert resp.status == 200
                assert resp.body == ("token=client-%d" % index).encode()
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    assert errors == []
    assert all(not thread.is_alive() for thread in threads)


def test_concurrent_connections_survive_garbage_mix(server_factory, make_client):
    cfg = Config(host="127.0.0.1", port=0, workers=16)
    srv = server_factory(config=cfg)
    errors = []

    def good(index):
        try:
            client = make_client(srv)
            resp = client.request("GET", "/echo/good-%d" % index)
            assert resp.body == ("token=good-%d" % index).encode()
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    def bad():
        try:
            client = make_client(srv)
            client.raw(b"GARBAGE\r\n\r\n")
        except Exception as exc:  # expected: connection closes
            pass

    jobs = []
    for index in range(8):
        jobs.append(threading.Thread(target=good, args=(index,)))
    for _ in range(4):
        jobs.append(threading.Thread(target=bad))
    for job in jobs:
        job.start()
    for job in jobs:
        job.join(timeout=15)
    assert errors == []


def test_idle_timeout_closes_connection(server_factory, make_client):
    cfg = Config(host="127.0.0.1", port=0, timeout=1.0)
    srv = server_factory(config=cfg)
    client = make_client(srv, timeout=5.0)
    # Send nothing; the server-side idle timeout must kick in.
    client.fp.close()
    assert client.sock.recv(16) == b""


def test_shutdown_closes_idle_connections(server_factory, make_client):
    cfg = Config(host="127.0.0.1", port=0, timeout=60)
    srv = server_factory(config=cfg)
    client = make_client(srv, timeout=10.0)
    client.sock.sendall(b"GET /hello HTTP/1.1\r\nHost: x\r\n\r\n")
    assert client.read_response().status == 200
    # Idle keep-alive connection must be closed promptly on shutdown.
    import time

    start = time.monotonic()
    srv.shutdown(wait=False)
    client.fp.close()
    assert client.sock.recv(16) == b""
    assert time.monotonic() - start < 5
