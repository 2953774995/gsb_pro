import socket
import threading
import time

import pytest

from gwadmin.app import Application
from gwadmin.server import BufferedSocket, HTTPServer


def loopback_available():
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", 0))
        probe.close()
        return True
    except OSError:
        probe.close()
        return False


LOOPBACK_AVAILABLE = loopback_available()


class ServerHandle:
    """Expose a uniform socket API for real TCP or socketpair transports.

    Normal environments bind a temporary TCP port. Some hardened CI sandboxes
    deny bind(); in that case socketpair still exercises the exact same
    BufferedSocket, parser, application and response serialization code.
    """

    def __init__(self, server):
        self.server = server
        self.mode = "tcp"
        self.thread = None
        if LOOPBACK_AVAILABLE:
            self.thread = threading.Thread(target=server.serve_forever, daemon=True)
            self.thread.start()
            time.sleep(0.03)
        else:
            self.mode = "pair"

    @property
    def port(self):
        return self.server.port

    def connect(self):
        if self.mode == "tcp":
            sock = socket.create_connection(("127.0.0.1", self.server.port), timeout=3)
        else:
            client, server_side = socket.socketpair()
            wrapper = BufferedSocket(server_side, ("socketpair", 0))
            self.server._worker_slots.acquire()
            with self.server._clients_lock:
                self.server._clients.add(wrapper)
            thread = threading.Thread(
                target=self.server._run_connection, args=(wrapper,), daemon=True
            )
            thread.start()
            sock = client
        sock.settimeout(3)
        return sock

    def stop(self):
        self.server.shutdown()
        if self.thread is not None:
            self.thread.join(timeout=3)


@pytest.fixture
def server_factory(tmp_path):
    handles = []

    def factory(app=None, workers=8, root=None, config_path=None, **kwargs):
        app = app or Application(
            root=str(root or tmp_path / "root"),
            config_path=str(config_path or tmp_path / "config.json"),
            worker_count=workers,
        )
        server = HTTPServer(
            app,
            host="127.0.0.1",
            port=0 if LOOPBACK_AVAILABLE else 1,
            workers=workers,
            idle_timeout=3,
            **kwargs,
        )
        if LOOPBACK_AVAILABLE:
            server.socket_pair()
        handle = ServerHandle(server)
        handles.append(handle)
        return handle

    yield factory
    for handle in handles:
        handle.stop()
