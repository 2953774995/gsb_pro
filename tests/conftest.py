import socket
import time

import pytest

from miniweb import Application, HTTPServer


class HTTPResponse:
    def __init__(self, status, headers, body, raw_head):
        self.status = status
        self.headers = headers  # dict with lower-cased names
        self.body = body
        self.raw_head = raw_head

    def header(self, name, default=None):
        return self.headers.get(name.lower(), default)


def read_response(sock):
    """Read one HTTP response from a socket."""
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionError("server closed connection before response")
        buf += chunk
    head, _, rest = buf.partition(b"\r\n\r\n")
    lines = head.decode("iso-8859-1").split("\r\n")
    status = int(lines[0].split(" ")[1])
    headers = {}
    for line in lines[1:]:
        name, _, value = line.partition(":")
        headers[name.strip().lower()] = value.strip()
    length = int(headers.get("content-length", 0))
    body = rest
    while len(body) < length:
        chunk = sock.recv(4096)
        if not chunk:
            break
        body += chunk
    return HTTPResponse(status, headers, body[:length], head)


def raw_exchange(port, data, shutdown_write=False):
    """Send raw bytes, read until the server closes the connection."""
    sock = socket.create_connection(("127.0.0.1", port), timeout=5)
    sock.sendall(data)
    if shutdown_write:
        sock.shutdown(socket.SHUT_WR)
    chunks = []
    try:
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
    except socket.timeout:
        pass
    finally:
        sock.close()
    return b"".join(chunks)


def make_request(port, method="GET", path="/", headers=None, body=b"",
                 version="HTTP/1.1", sock=None):
    """Send one request; return (response, sock). Reuses sock if given."""
    if sock is None:
        sock = socket.create_connection(("127.0.0.1", port), timeout=5)
    hdrs = {"Host": "127.0.0.1"}
    hdrs.update(headers or {})
    if body and "Content-Length" not in hdrs:
        hdrs["Content-Length"] = str(len(body))
    lines = ["%s %s %s" % (method, path, version)]
    lines += ["%s: %s" % kv for kv in hdrs.items()]
    if isinstance(body, str):
        body = body.encode()
    sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode() + body)
    return read_response(sock), sock


@pytest.fixture
def app():
    application = Application()

    @application.get("/hello")
    def hello(request):
        return 200, {"Content-Type": "text/plain"}, "hello"

    @application.get("/users/:id")
    def user(request):
        return 200, {"Content-Type": "text/plain"}, "user:%s" % request.path_params["id"]

    @application.post("/submit")
    def submit(request):
        return 200, {"Content-Type": "text/plain"}, "submitted"

    @application.put("/item")
    def put_item(request):
        return 200, {}, "put"

    @application.delete("/item")
    def delete_item(request):
        return 200, {}, "deleted"

    @application.get("/boom")
    def boom(request):
        raise RuntimeError("secret internal failure")

    @application.get("/slow")
    def slow(request):
        time.sleep(0.1)
        return 200, {}, "slow"

    @application.get("/echo/:name")
    def echo_name(request):
        return 200, {}, request.path_params["name"]

    return application


@pytest.fixture
def server(app):
    srv = HTTPServer(app, host="127.0.0.1", port=0, workers=16, timeout=5)
    srv.start()
    yield srv
    srv.shutdown()


@pytest.fixture
def port(server):
    return server.port
