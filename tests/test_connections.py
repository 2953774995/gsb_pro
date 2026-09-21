import json
import socket
import threading

from gwadmin.app import Application


def recv_until_headers(sock):
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(4096)
        if not chunk:
            raise AssertionError("connection closed before headers")
        data += chunk
    head, extra = data.split(b"\r\n\r\n", 1)
    length = 0
    for line in head.split(b"\r\n")[1:]:
        if line.lower().startswith(b"content-length:"):
            length = int(line.split(b":", 1)[1].strip())
    body = extra
    while len(body) < length:
        body += sock.recv(length - len(body))
    return head + b"\r\n\r\n" + body[:length], body[length:]


def test_keep_alive_two_requests_same_connection(server_factory, tmp_path):
    app = Application(root=str(tmp_path / "root"), config_path=str(tmp_path / "c.json"))
    app.router.get("/hello/:name", lambda r: (200, {"Content-Type": "text/plain"}, r.params["name"]))
    server = server_factory(app=app)
    sock = server.connect()
    sock.settimeout(3)
    sock.sendall(b"GET /hello/alpha HTTP/1.1\r\nHost: gw\r\n\r\n")
    first, leftover = recv_until_headers(sock)
    assert b"HTTP/1.1 200" in first and b"connection: keep-alive" in first.lower()
    assert b"alpha" in first
    assert leftover == b""
    sock.sendall(b"GET /hello/beta HTTP/1.1\r\nHost: gw\r\nConnection: close\r\n\r\n")
    second = sock.recv(4096)
    assert b"beta" in second and b"connection: close" in second.lower()
    sock.close()


def test_connection_close_header_and_http_10_default(server_factory, tmp_path):
    server = server_factory(root=tmp_path / "root", config_path=tmp_path / "c.json")
    sock = server.connect()
    sock.settimeout(3)
    sock.sendall(b"GET /api/status HTTP/1.0\r\n\r\n")
    raw = b""
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            break
        raw += chunk
    sock.close()
    assert b"HTTP/1.0 200" in raw
    assert b"connection: close" in raw.lower()


def test_many_concurrent_connections_do_not_crash_or_mix(server_factory, tmp_path):
    app = Application(root=str(tmp_path / "root"), config_path=tmp_path / "c.json", worker_count=24)
    app.router.get("/item/:id", lambda r: (200, {"Content-Type": "text/plain"}, r.params["id"]))
    server = server_factory(app=app, workers=24)
    errors = []
    barrier = threading.Barrier(16)

    def worker(i):
        try:
            barrier.wait(3)
            sock = server.connect()
            sock.settimeout(5)
            token = f"token-{i:02d}"
            sock.sendall(
                f"GET /item/{token} HTTP/1.1\r\nHost: gw\r\nConnection: close\r\n\r\n".encode()
            )
            chunks = []
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                chunks.append(chunk)
            sock.close()
            raw = b"".join(chunks)
            assert b"HTTP/1.1 200" in raw
            assert token.encode() in raw
            # Each full body should contain exactly one token and no other token.
            body = raw.split(b"\r\n\r\n", 1)[1]
            assert body.count(b"token-") == 1
        except Exception as exc:  # report thread failures on main thread
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(16)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)
    assert not errors
    # Service remains available after concurrency burst.
    sock = server.connect()
    sock.settimeout(3)
    sock.sendall(b"GET /api/status HTTP/1.1\r\nHost: gw\r\nConnection: close\r\n\r\n")
    raw = b""
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            break
        raw += chunk
    sock.close()
    assert json.loads(raw.split(b"\r\n\r\n", 1)[1])["requests_handled"] >= 16


def test_clean_shutdown_closes_listener_and_connections(server_factory, tmp_path):
    import signal

    server = server_factory(root=tmp_path / "root", config_path=tmp_path / "c.json")
    if server.mode != "tcp":
        return
    server.server.install_signal_handlers()
    signal.raise_signal(signal.SIGINT)
    server.thread.join(timeout=3)
    assert not server.thread.is_alive()
