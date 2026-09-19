"""Shared fixtures: a real miniweb server on an ephemeral port.

Every test talks to the server over a genuine TCP socket (no
http.client / requests involved), exactly as the PRD requires.  In
sandboxed environments where the OS forbids socket binding, the server
fixture skips gracefully; ``test_pair_transport.py`` still exercises the
same connection-handling code via socketpair.
"""

import json
import socket
import threading
import time

import pytest

from miniweb import Config, HTTPError, HttpServer, MiniWeb, Request, Response

STATIC_ROOT = __import__("os").path.join(
    __import__("os").path.dirname(__file__), "static"
)


def build_app(static_root: str = STATIC_ROOT) -> MiniWeb:
    app = MiniWeb(static_root=static_root)

    @app.get("/hello")
    def hello(request):
        name = request.query.get("name", ["world"])[0]
        return 200, {"Content-Type": "text/plain; charset=utf-8"}, "hi %s" % name

    @app.get("/users/:id")
    def user_detail(request):
        return (
            200,
            {"Content-Type": "application/json"},
            json.dumps({"id": request.params["id"]}),
        )

    @app.post("/echo")
    def echo(request):
        if request.content_type == "application/json":
            return 200, {"Content-Type": "application/json"}, request.body
        payload = {
            k: (v[0] if len(v) == 1 else v) for k, v in request.form.items()
        }
        return 200, {"Content-Type": "application/json"}, json.dumps(payload)

    @app.put("/users/:id")
    def update_user(request):
        return (
            200,
            {"Content-Type": "application/json"},
            json.dumps({"updated": request.params["id"], "body": request.body.decode()}),
        )

    @app.delete("/users/:id")
    def delete_user(request):
        return (
            200,
            {"Content-Type": "application/json"},
            json.dumps({"deleted": request.params["id"]}),
        )

    @app.get("/boom")
    def boom(request):
        raise RuntimeError("kaboom")

    @app.get("/redirect")
    def redirect(request):
        raise HTTPError(302, headers={"Location": "/hello"})

    @app.get("/echo/:token")
    def echo_token(request):
        return (
            200,
            {"Content-Type": "text/plain; charset=utf-8"},
            "token=%s" % request.params["token"],
        )

    @app.post("/json/check")
    def json_check(request):
        data = request.json
        return 200, {"Content-Type": "application/json"}, json.dumps({"ok": data})

    return app


class RawClient:
    """Minimal HTTP/1.1 client over a single persistent socket."""

    def __init__(self, host: str, port: int, timeout: float = 5.0):
        self.host = host
        self.port = port
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.fp = self.sock.makefile("rb")

    def raw(self, data: bytes, read_response: bool = True):
        self.sock.sendall(data)
        if not read_response:
            return None
        return self.read_response()

    def request(
        self,
        method: str,
        path: str,
        headers=None,
        body=b"",
        auto_length: bool = True,
        version: str = "HTTP/1.1",
        read_body: bool = True,
    ):
        if isinstance(body, str):
            body = body.encode()
        lines = ["%s %s %s" % (method, path, version)]
        lines.append("Host: %s:%d" % (self.host, self.port))
        sent_length = False
        for name, value in (headers or []):
            lines.append("%s: %s" % (name, value))
            if name.lower() == "content-length":
                sent_length = True
        if body and auto_length and not sent_length:
            lines.append("Content-Length: %d" % len(body))
        raw = ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1") + body
        self.sock.sendall(raw)
        return self.read_response(read_body=read_body and method != "HEAD")

    def read_response(self, read_body: bool = True):
        status_line = self.fp.readline()
        if not status_line:
            raise ConnectionError("server closed connection without response")
        parts = status_line.decode("latin-1").rstrip("\r\n").split(" ", 2)
        version = parts[0]
        status = int(parts[1])
        # Skip interim responses such as "100 Continue".
        while 100 <= status < 200:
            while True:
                interim = self.fp.readline()
                if interim in (b"\r\n", b"\n", b""):
                    break
            status_line = self.fp.readline()
            parts = status_line.decode("latin-1").rstrip("\r\n").split(" ", 2)
            version = parts[0]
            status = int(parts[1])
        reason = parts[2] if len(parts) > 2 else ""
        headers = {}
        while True:
            line = self.fp.readline()
            if line in (b"\r\n", b"\n", b""):
                break
            name, _, value = line.decode("latin-1").rstrip("\r\n").partition(":")
            headers[name.lower()] = value.strip()
        length = int(headers.get("content-length", "0"))
        body = self.fp.read(length) if (length and read_body) else b""
        return ParsedResponse(status, reason, headers, body, version)

    def close(self):
        try:
            self.fp.close()
        finally:
            self.sock.close()


class ParsedResponse:
    def __init__(self, status, reason, headers, body, version):
        self.status = status
        self.reason = reason
        self.headers = headers
        self.body = body
        self.version = version

    def json(self):
        return json.loads(self.body.decode())


class PairServer:
    """In-process stand-in for HttpServer using socketpair transports."""

    def __init__(self, app, config):
        self.app = app
        self.config = config
        self.pairs = []
        import threading as _threading
        self._lock = _threading.Lock()
        self.closed = False

    def new_client(self, timeout=None):
        pair = PairClient(self.app, self.config, timeout=timeout or
                          self.config.timeout)
        with self._lock:
            self.pairs.append(pair)
        return pair

    def shutdown(self, wait=True):
        self.closed = True
        import time as _time
        with self._lock:
            pairs = list(self.pairs)
        deadline = _time.time() + 5
        for pair in pairs:
            try:
                pair._socks[1].shutdown(socket.SHUT_WR)
            except OSError:
                pass
        if wait:
            for pair in pairs:
                remaining = max(0.0, deadline - _time.time())
                pair.join(remaining)
        for pair in pairs:
            try:
                pair._socks[1].close()
            except OSError:
                pass

    # HttpServer.address stand-in (host/port only used for Host header).
    @property
    def address(self):
        return ("pair", 0)


def _tcp_allowed():
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", 0))
        probe.close()
        return True
    except OSError:
        return False


TCP_OK = _tcp_allowed()


@pytest.fixture
def server_factory():
    servers = []

    def _make(app=None, config=None, wait_ready=True):
        cfg = config or Config(host="127.0.0.1", port=0, workers=8, timeout=5)
        if app is None and not cfg.static_root:
            cfg.static_root = STATIC_ROOT
        application = app or build_app(cfg.static_root)
        if not TCP_OK:
            srv = PairServer(application, cfg)
            servers.append(srv)
            return srv
        srv = HttpServer(application, cfg)
        srv.listen()
        srv.start_in_thread()
        servers.append(srv)
        return srv

    yield _make

    for srv in servers:
        srv.shutdown(wait=False)


@pytest.fixture
def server(server_factory):
    return server_factory()


@pytest.fixture
def make_client():
    clients = []

    def _make(srv, timeout=5.0):
        if isinstance(srv, PairServer):
            client = srv.new_client(timeout=timeout)
            clients.append(client)
            return client
        host, port = srv.address
        client = RawClient(host, port, timeout=timeout)
        clients.append(client)
        return client

    yield _make

    for client in clients:
        client.close()


@pytest.fixture
def client(server, make_client):
    return make_client(server)


class PairClient:
    """Drive ``MiniWeb.handle_connection`` through a real socketpair.

    The byte-level transport is identical to TCP; only the addressing
    differs.  Lets connection parsing/keep-alive/concurrency be verified
    in sandboxes that forbid TCP bind().
    """

    def __init__(self, app, config=None, timeout=10.0):
        import socket as _socket

        from miniweb import Config

        self.config = config or Config(timeout=timeout)
        client_sock, server_sock = _socket.socketpair()
        client_sock.settimeout(timeout)
        server_sock.settimeout(self.config.timeout)
        self.sock = client_sock
        self.fp = client_sock.makefile("rb")
        self._reader = server_sock.makefile("rb")
        self._writer = server_sock.makefile("wb")
        self._socks = (client_sock, server_sock)
        self.thread = threading.Thread(
            target=app.handle_connection,
            args=(
                self._reader,
                self._writer,
                ("pair", 0),
                self.config,
                server_sock,
            ),
            daemon=True,
        )
        self.thread.start()

    def raw(self, data: bytes, read_body: bool = True):
        self.sock.sendall(data)
        return self.read_response(read_body=read_body)

    def request(self, method, path, headers=None, body=b"", version="HTTP/1.1",
                read_body: bool = True):
        if isinstance(body, str):
            body = body.encode()
        lines = ["%s %s %s" % (method, path, version), "Host: pair"]
        sent_length = False
        for name, value in headers or []:
            lines.append("%s: %s" % (name, value))
            if name.lower() == "content-length":
                sent_length = True
        if body and not sent_length:
            lines.append("Content-Length: %d" % len(body))
        self.sock.sendall(
            ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1") + body
        )
        return self.read_response(read_body=read_body and method != "HEAD")

    def read_response(self, read_body: bool = True):
        status_line = self.fp.readline()
        if not status_line:
            raise ConnectionError("connection closed")
        parts = status_line.decode("latin-1").rstrip("\r\n").split(" ", 2)
        status = int(parts[1])
        while 100 <= status < 200:
            while True:
                interim = self.fp.readline()
                if interim in (b"\r\n", b"\n", b""):
                    break
            status_line = self.fp.readline()
            parts = status_line.decode("latin-1").rstrip("\r\n").split(" ", 2)
            status = int(parts[1])
        headers = {}
        while True:
            line = self.fp.readline()
            if line in (b"\r\n", b"\n", b""):
                break
            name, _, value = line.decode("latin-1").rstrip("\r\n").partition(":")
            headers[name.lower()] = value.strip()
        length = int(headers.get("content-length", "0"))
        body = self.fp.read(length) if (length and read_body) else b""
        return ParsedResponse(status, parts[2] if len(parts) > 2 else "",
                              headers, body, parts[0])

    def join(self, timeout=10.0):
        self.thread.join(timeout)

    def close(self):
        for sock in self._socks:
            try:
                sock.close()
            except OSError:
                pass
