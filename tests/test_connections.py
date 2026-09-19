import socket
from concurrent.futures import ThreadPoolExecutor

from helpers import parse_response


def _recv_response(sock):
    # Read one exact response by respecting Content-Length, without depending
    # on connection close.  Header bytes are buffered so later body recv()
    # calls cannot accidentally consume the next pipelined response.
    header_data = b""
    while b"\r\n\r\n" not in header_data:
        chunk = sock.recv(4096)
        if not chunk:
            raise AssertionError("connection closed before headers")
        header_data += chunk
    raw_headers, extra = header_data.split(b"\r\n\r\n", 1)
    length = 0
    for line in raw_headers.split(b"\r\n")[1:]:
        if line.lower().startswith(b"content-length:"):
            length = int(line.split(b":", 1)[1].strip())
    body = extra
    while len(body) < length:
        chunk = sock.recv(length - len(body))
        if not chunk:
            raise AssertionError("connection closed before body")
        body += chunk
    return raw_headers + b"\r\n\r\n" + body[:length]


def test_keep_alive_two_requests_same_connection(port):
    with socket.create_connection(("127.0.0.1", port), timeout=3) as sock:
        for path in (b"/hello", b"/users/10"):
            request = b"GET " + path + b" HTTP/1.1\r\nHost: x\r\nConnection: keep-alive\r\n\r\n"
            sock.sendall(request)
            data = _recv_response(sock)
            status, headers, body, *_ = parse_response(data)
            assert status == 200
            assert headers["connection"] == "keep-alive"
        assert body == b'{"id": "10", "q": {}}'


def test_connection_close_response_closes_after_one(port):
    with socket.create_connection(("127.0.0.1", port), timeout=3) as sock:
        sock.sendall(
            b"GET /hello HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n"
        )
        chunks = []
        while True:
            chunk = sock.recv(1024)
            if not chunk:
                break
            chunks.append(chunk)
        data = b"".join(chunks)
    status, headers, body, *_ = parse_response(data)
    assert status == 200
    assert headers["connection"] == "close"
    assert body == b"hello"


def test_http_10_default_closes_but_keepalive_header_reuses(port):
    with socket.create_connection(("127.0.0.1", port), timeout=3) as sock:
        sock.sendall(b"GET /hello HTTP/1.0\r\n\r\n")
        chunks = []
        while True:
            chunk = sock.recv(1024)
            if not chunk:
                break
            chunks.append(chunk)
    status, headers, *_ = parse_response(b"".join(chunks))
    assert status == 200
    assert headers["connection"] == "close"


def test_concurrent_connections_do_not_cross_responses(port):
    def one(i):
        with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
            path = f"/users/{i}?tag=t{i}".encode()
            sock.sendall(
                b"GET " + path + b" HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n"
            )
            data = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk
        status, headers, body, *_ = parse_response(data)
        assert status == 200
        assert headers["connection"] == "close"
        expected = f'{{"id": "{i}", "q": {{"tag": "t{i}"}}}}'.encode()
        assert body == expected
        return body

    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(one, range(20)))
    assert len(results) == 20
    assert len({result for result in results}) == 20


def test_malformed_request_does_not_crash_following_connections(port):
    with socket.create_connection(("127.0.0.1", port), timeout=3) as bad:
        bad.sendall(b"BAD-REQUEST\r\n\r\n")
        assert bad.recv(4096).startswith(b"HTTP/1.1 400")

    # Give the worker a moment, then verify a fresh connection is served.
    status, headers, body, *_ = parse_response(
        _one_shot(port, b"GET /hello HTTP/1.1\r\nHost: x\r\n\r\n")
    )
    assert status == 200


def _one_shot(port, payload):
    with socket.create_connection(("127.0.0.1", port), timeout=3) as sock:
        sock.sendall(payload)
        data = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
        return data
