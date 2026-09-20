"""Hand-rolled HTTP client helpers for tests (raw sockets only).

All helpers take a ``connect`` callable (provided by the ``env`` fixture)
that returns a fresh client socket connected to the server under test.
"""

import socket


def read_response(sock, head_only=False):
    """Read one HTTP response. Returns (status, headers_dict, body_bytes)."""
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            raise AssertionError("connection closed before response head")
        buf += chunk
    head, rest = buf.split(b"\r\n\r\n", 1)
    lines = head.decode("iso-8859-1").split("\r\n")
    status = int(lines[0].split(" ")[1])
    headers = {}
    for line in lines[1:]:
        name, value = line.split(":", 1)
        headers.setdefault(name.strip().lower(), value.strip())
    length = 0 if head_only else int(headers.get("content-length", 0))
    body = rest
    while len(body) < length:
        chunk = sock.recv(4096)
        if not chunk:
            raise AssertionError("connection closed before response body")
        body += chunk
    return status, headers, body[:length]


def request(connect, method="GET", path="/", headers=None, body=b"",
            version="HTTP/1.1", sock=None):
    """Send one request (optionally on an existing keep-alive socket)."""
    own = sock is None
    if own:
        sock = connect()
    if isinstance(body, str):
        body = body.encode("utf-8")
    lines = ["%s %s %s" % (method, path, version),
             "Host: 127.0.0.1"]
    for name, value in (headers or {}).items():
        lines.append("%s: %s" % (name, value))
    if body and not any(k.lower() == "content-length" for k in (headers or {})):
        lines.append("Content-Length: %d" % len(body))
    raw = ("\r\n".join(lines) + "\r\n\r\n").encode("iso-8859-1") + body
    sock.sendall(raw)
    result = read_response(sock, head_only=(method.upper() == "HEAD"))
    if own:
        sock.close()
    return result


def raw_exchange(connect, payload, shutdown_write=False, wait=2.0):
    """Send raw bytes; read until the server closes the connection."""
    sock = connect()
    sock.sendall(payload)
    if shutdown_write:
        sock.shutdown(socket.SHUT_WR)
    chunks = []
    try:
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
    except (socket.timeout, TimeoutError):
        pass
    finally:
        sock.close()
    return b"".join(chunks)
