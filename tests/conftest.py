import os
import socket
import sys
import threading

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gwadmin.app import GwAdminApp
from gwadmin.server import GatewayServer


@pytest.fixture()
def www_root(tmp_path):
    root = tmp_path / "www"
    root.mkdir()
    (root / "index.html").write_text(
        "<!DOCTYPE html><html><body><h1>gwadmin</h1></body></html>",
        encoding="utf-8")
    (root / "style.css").write_text("body { margin: 0; }", encoding="utf-8")
    (root / "app.js").write_text("console.log('gw');", encoding="utf-8")
    (root / "notes.txt").write_text("hello gateway\n", encoding="utf-8")
    (root / "data.json").write_text('{"a": 1}', encoding="utf-8")
    sub = root / "sub"
    sub.mkdir()
    (sub / "index.html").write_text("<h1>sub</h1>", encoding="utf-8")
    (root / "emptydir").mkdir()
    return root


@pytest.fixture()
def app(www_root, tmp_path):
    return GwAdminApp(root=str(www_root),
                      config_path=str(tmp_path / "config.json"),
                      workers=4)


class TcpTransport(object):
    """Real server bound to an ephemeral TCP port (the PRD default)."""

    mode = "tcp"

    def __init__(self, app):
        self.server = GatewayServer(app, host="127.0.0.1", port=0,
                                    workers=4, idle_timeout=5.0)
        self.server.start()
        self.port = self.server.port
        self._thread = threading.Thread(target=self.server.serve_forever,
                                        daemon=True)
        self._thread.start()

    def connect(self):
        return socket.create_connection(("127.0.0.1", self.port), timeout=10)

    def shutdown(self):
        self.server.shutdown()


class SocketPairTransport(object):
    """Fallback for sandboxes that forbid bind(): drives the very same
    GatewayServer per-connection worker over socketpairs."""

    mode = "socketpair"

    def __init__(self, app):
        self.server = GatewayServer(app, host="127.0.0.1", port=0,
                                    workers=4, idle_timeout=5.0)
        self.port = 0
        self._threads = []

    def connect(self):
        client, server_end = socket.socketpair()
        client.settimeout(10)
        thread = threading.Thread(
            target=self.server._connection_worker,
            args=(server_end, ("127.0.0.1", 0)), daemon=True)
        thread.start()
        self._threads.append(thread)
        return client

    def shutdown(self):
        self.server.shutdown()


@pytest.fixture()
def env(app):
    try:
        transport = TcpTransport(app)
    except PermissionError:
        transport = SocketPairTransport(app)
    yield transport
    transport.shutdown()
