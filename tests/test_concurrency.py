"""Concurrent connections: 10+ simultaneous clients, no crashes or mixups."""

import threading

from conftest import make_request


def test_concurrent_requests(port):
    n = 12
    barrier = threading.Barrier(n)
    results = [None] * n
    errors = []

    def worker(i):
        name = "worker%d" % i
        try:
            barrier.wait(timeout=5)
            for _ in range(3):
                resp, sock = make_request(port, "GET", "/echo/" + name)
                sock.close()
                assert resp.status == 200
                assert resp.body == name.encode()
            results[i] = True
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    assert not errors
    assert all(results)


def test_concurrent_slow_requests_all_succeed(port):
    n = 10
    barrier = threading.Barrier(n)
    outcomes = []

    def worker():
        barrier.wait(timeout=5)
        resp, sock = make_request(port, "GET", "/slow")
        sock.close()
        outcomes.append((resp.status, resp.body))

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    assert outcomes == [(200, b"slow")] * n
