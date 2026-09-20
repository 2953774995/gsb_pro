"""Keep-alive reuse, concurrency, and graceful shutdown tests."""

import json
import socket
import threading
import time

from helpers import request, read_response


def test_keep_alive_two_requests_same_connection(env):
    sock = env.connect()
    try:
        s1, h1, b1 = request(env.connect, "GET", "/api/status", sock=sock)
        assert s1 == 200
        assert h1["connection"] == "keep-alive"
        s2, h2, b2 = request(env.connect, "GET", "/notes.txt", sock=sock)
        assert s2 == 200
        assert b2 == b"hello gateway\n"
    finally:
        sock.close()


def test_keep_alive_many_requests_same_connection(env):
    sock = env.connect()
    try:
        for i in range(5):
            status, _, body = request(env.connect, "GET",
                                      "/api/status?n=%d" % i, sock=sock)
            assert status == 200
            assert json.loads(body)["status"] == "ok"
    finally:
        sock.close()


def test_keep_alive_post_then_get(env):
    sock = env.connect()
    try:
        s1, _, _ = request(env.connect, "POST", "/api/config",
                           headers={"Content-Type": "application/json"},
                           body=json.dumps({"sampling_interval_ms": 300}),
                           sock=sock)
        assert s1 == 200
        s2, _, body = request(env.connect, "GET", "/api/config", sock=sock)
        assert s2 == 200
        assert json.loads(body)["sampling_interval_ms"] == 300
    finally:
        sock.close()


def test_connection_close_actually_closes(env):
    sock = env.connect()
    request(env.connect, "GET", "/",
            headers={"Connection": "close"}, sock=sock)
    # Server must close the connection after the response.
    assert sock.recv(1) == b""
    sock.close()


def test_pipelined_requests(env):
    """Two requests sent back-to-back on one connection get two responses."""
    sock = env.connect()
    try:
        raw = (b"GET /api/status HTTP/1.1\r\nHost: x\r\n\r\n"
               b"GET /notes.txt HTTP/1.1\r\nHost: x\r\n"
               b"Connection: close\r\n\r\n")
        sock.sendall(raw)
        s1, _, _ = read_response(sock)
        s2, _, b2 = read_response(sock)
        assert s1 == 200
        assert s2 == 200
        assert b2 == b"hello gateway\n"
    finally:
        sock.close()


def test_concurrent_connections(env):
    """10+ simultaneous connections, each gets its own correct response."""
    results = []
    errors = []
    barrier = threading.Barrier(12)

    def worker(i):
        try:
            path = "/api/status" if i % 2 == 0 else "/notes.txt"
            barrier.wait(timeout=10)
            status, _, body = request(env.connect, "GET", path)
            if path == "/api/status":
                ok = status == 200 and json.loads(body)["status"] == "ok"
            else:
                ok = status == 200 and body == b"hello gateway\n"
            results.append(ok)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not errors, errors
    assert len(results) == 12
    assert all(results)


def test_concurrent_keep_alive_sessions(env):
    """Concurrent clients each reusing their own connection; no crosstalk."""
    errors = []

    def worker(i):
        try:
            sock = env.connect()
            try:
                for n in range(3):
                    path = "/api/devices/gw-%d-%d" % (i, n)
                    status, _, body = request(env.connect, "GET", path,
                                              sock=sock)
                    assert status == 200
                    assert json.loads(body)["id"] == "gw-%d-%d" % (i, n)
            finally:
                sock.close()
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not errors, errors


def test_idle_connection_times_out(app):
    """A connection that sends nothing is closed after the idle timeout."""
    from gwadmin.server import GatewayServer
    import socket as _socket
    try:
        srv = GatewayServer(app, host="127.0.0.1", port=0, workers=2,
                            idle_timeout=0.3)
        srv.start()
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        sock = _socket.create_connection(("127.0.0.1", srv.port), timeout=5)
    except PermissionError:
        import pytest
        pytest.skip("sandbox forbids bind(); idle timeout covered by unit "
                    "semantics elsewhere")
    try:
        deadline = time.time() + 5
        closed = False
        while time.time() < deadline:
            try:
                data = sock.recv(1)
            except _socket.timeout:
                continue
            if data == b"":
                closed = True
                break
        assert closed, "server did not close the idle connection"
    finally:
        sock.close()
        srv.shutdown()


def test_graceful_shutdown(app):
    """shutdown() stops accepting and closes existing connections."""
    from gwadmin.server import GatewayServer
    try:
        srv = GatewayServer(app, host="127.0.0.1", port=0, workers=2,
                            idle_timeout=30.0)
        srv.start()
    except PermissionError:
        import pytest
        pytest.skip("sandbox forbids bind()")
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()

    sock = socket.create_connection(("127.0.0.1", srv.port), timeout=5)
    status, _, _ = request(None, "GET", "/api/status", sock=sock)
    assert status == 200

    srv.shutdown()
    thread.join(timeout=5)
    assert not thread.is_alive()
    # Existing connection is closed by the server.
    sock.settimeout(5)
    assert sock.recv(1) == b""
    sock.close()
    # New connections are refused.
    try:
        socket.create_connection(("127.0.0.1", srv.port), timeout=2)
        refused = False
    except OSError:
        refused = True
    assert refused
