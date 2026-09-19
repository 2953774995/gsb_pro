"""Concurrency: many simultaneous connections, no crashes, no crosstalk."""

import socket
import threading

from conftest import open_conn, read_response, request, start_server


def test_concurrent_connections(addr):
    errors = []
    results = {}

    def worker(i):
        try:
            for round_ in range(3):
                payload = ("client-%d-round-%d" % (i, round_)).encode()
                status, _, body = request(
                    addr, "POST", "/echo",
                    headers={"Content-Type": "application/octet-stream"},
                    body=payload)
                assert status == 200
                assert body == payload, "crosstalk: %r != %r" % (body, payload)
                results[(i, round_)] = body
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(15)

    assert not errors, errors
    assert len(results) == 16 * 3


def test_concurrent_keepalive_connections(addr):
    errors = []

    def worker(i):
        try:
            sock, rfile = open_conn(addr)
            try:
                for n in range(5):
                    path = "/users/%d" % (i * 100 + n)
                    sock.sendall(
                        ("GET %s HTTP/1.1\r\nHost: x\r\n\r\n" % path)
                        .encode("latin-1"))
                    status, _, body = read_response(rfile)
                    assert status == 200
                    assert body == ("user:%d" % (i * 100 + n)).encode()
            finally:
                sock.close()
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(15)
    assert not errors, errors


def test_server_alive_after_connection_storm(addr):
    def hammer():
        try:
            sock = socket.create_connection(addr, timeout=5)
            sock.sendall(b"GET /hello HTTP/1.1\r\nHost: x\r\n\r\n")
            sock.close()  # close without reading
        except OSError:
            pass

    threads = [threading.Thread(target=hammer) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)

    status, _, body = request(addr, "GET", "/hello")
    assert status == 200 and body == b"hello"
