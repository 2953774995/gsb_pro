import socket
import threading
import time

import pytest

from miniweb import Application, HTTPServer


# ---------------------------------------------------------------------------
# raw-socket client helpers (tests talk to a real server on a real port)
# ---------------------------------------------------------------------------

def read_response(rfile):
    """Read one HTTP response from a socket file. Returns
    (status, headers_dict, body_bytes)."""
    status_line = rfile.readline().decode("latin-1").rstrip("\r\n")
    assert status_line, "connection closed before status line"
    version, status, _reason = status_line.split(" ", 2)
    headers = {}
    while True:
        line = rfile.readline().decode("latin-1")
        if line in ("\r\n", "\n", ""):
            break
        name, value = line.split(":", 1)
        headers[name.strip().lower()] = value.strip()
    body = b""
    if "content-length" in headers:
        body = rfile.read(int(headers["content-length"]))
    elif headers.get("connection", "").lower() == "close":
        body = rfile.read()
    return int(status), headers, body


# Connectors for environments where binding TCP sockets is not permitted
# (e.g. restricted sandboxes).  Keyed by (host, port).
_CONNECTORS = {}


def open_conn(addr):
    connector = _CONNECTORS.get(addr)
    if connector is not None:
        return connector()
    sock = socket.create_connection(addr, timeout=5)
    return sock, sock.makefile("rb")


def raw_connect(addr):
    """A bare connected socket (for raw-byte tests)."""
    connector = _CONNECTORS.get(addr)
    if connector is not None:
        sock, _file = connector()
        return sock
    return socket.create_connection(addr, timeout=5)


def request(addr, method="GET", path="/", headers=None, body=b"",
            version="HTTP/1.1", close=True):
    """One-shot request on a fresh connection. Returns
    (status, headers, body)."""
    if isinstance(body, str):
        body = body.encode("utf-8")
    hdrs = {"Host": "localhost", "Connection": "close" if close else "keep-alive"}
    hdrs.update(headers or {})
    if body and "Content-Length" not in hdrs:
        hdrs["Content-Length"] = str(len(body))
    lines = ["%s %s %s" % (method, path, version)]
    lines += ["%s: %s" % kv for kv in hdrs.items()]
    payload = ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1") + body

    sock, rfile = open_conn(addr)
    try:
        sock.sendall(payload)
        return read_response(rfile)
    finally:
        sock.close()


def raw_request(addr, data, shutdown_write=False):
    """Send raw bytes, read the response until the server closes the
    connection. Returns the raw response bytes."""
    sock = raw_connect(addr)
    try:
        sock.sendall(data)
        if shutdown_write:
            sock.shutdown(socket.SHUT_WR)
        chunks = []
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        sock.close()


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

def make_test_app():
    app = Application()

    @app.get("/hello")
    def hello(request):
        return 200, [], "hello"

    @app.get("/users/:id")
    def user(request):
        return 200, [("Content-Type", "text/plain")], \
            "user:%s" % request.path_params["id"]

    @app.get("/echo-args")
    def echo_args(request):
        parts = sorted("%s=%s" % (k, ",".join(v))
                       for k, v in request.args.items())
        return 200, [("Content-Type", "text/plain")], "&".join(parts)

    @app.post("/submit")
    def submit(request):
        form = request.form
        parts = sorted("%s=%s" % (k, ",".join(v)) for k, v in form.items())
        return 200, [("Content-Type", "text/plain")], "&".join(parts)

    @app.post("/json")
    def json_echo(request):
        data = request.json
        import json
        return 200, [("Content-Type", "application/json")], \
            json.dumps({"got": data}, sort_keys=True)

    @app.put("/items/:id")
    def put_item(request):
        return 200, [], "put:%s" % request.path_params["id"]

    @app.delete("/items/:id")
    def delete_item(request):
        return 200, [], "delete:%s" % request.path_params["id"]

    @app.post("/echo")
    def echo(request):
        return 200, [("Content-Type", "application/octet-stream")], \
            request.body

    @app.get("/boom")
    def boom(request):
        raise RuntimeError("secret internal explosion")

    @app.get("/old-page")
    def old_page(request):
        return 301, [("Location", "/hello")], None

    @app.get("/found")
    def found(request):
        return 302, [("Location", "/hello")], None

    return app


class ServerHandle(object):
    def __init__(self, server, thread):
        self.server = server
        self.thread = thread

    @property
    def addr(self):
        return (self.server.host, self.server.port)


def _tcp_listen_allowed():
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.bind(("127.0.0.1", 0))
        probe.close()
        return True
    except OSError:
        return False


_TCP_OK = _tcp_listen_allowed()
_FAKE_PORT = [40000]


def start_server(app=None, **kwargs):
    """Start a real server.  Uses a real TCP listener on an ephemeral
    port whenever the environment allows it; otherwise falls back to
    socketpair transport driving the very same server code."""
    app = app if app is not None else make_test_app()
    kwargs.setdefault("idle_timeout", 30.0)
    server = HTTPServer("127.0.0.1", 0, app, **kwargs)
    if _TCP_OK:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        deadline = time.time() + 5
        while server.port == 0 and time.time() < deadline:
            time.sleep(0.01)
        assert server.port != 0, "server failed to start"
        return ServerHandle(server, thread)

    # -- socketpair fallback (sandboxed environments) -----------------------
    _FAKE_PORT[0] += 1
    server.port = _FAKE_PORT[0]

    def connector(server=server):
        a, b = socket.socketpair()
        t = threading.Thread(target=server._connection_runner,
                             args=(a, ("127.0.0.1", 0)), daemon=True)
        t.start()
        return b, b.makefile("rb")

    _CONNECTORS[server.host, server.port] = connector
    return ServerHandle(server, None)


@pytest.fixture
def server():
    handle = start_server()
    yield handle
    handle.server.shutdown()


@pytest.fixture
def addr(server):
    return server.addr
