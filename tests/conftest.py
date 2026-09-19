"""Shared pytest fixtures.

The integration tests run against a real TCP server whenever the
environment permits binding to 127.0.0.1.  In restricted sandboxes where
TCP loopback is not allowed, the exact same tests are executed over
``socket.socketpair()`` connections injected directly into the server, so
the full protocol/client/server stack is still exercised end to end.
"""

import socket
import time

import pytest

from minibroker.client import BrokerClient
from minibroker.server import BrokerServer


def _tcp_available():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        s.close()
        return True
    except OSError:
        return False


TCP_AVAILABLE = _tcp_available()


class ServerHandle:
    """Uniform handle over a BrokerServer regardless of the transport."""

    def __init__(self, **kwargs):
        kwargs.setdefault("host", "127.0.0.1")
        kwargs.setdefault("port", 0)
        self.server = BrokerServer(**kwargs)
        self.tcp = TCP_AVAILABLE
        if self.tcp:
            self.server.start()

    # -- attributes proxied to the server --------------------------------
    @property
    def host(self):
        return self.server.host

    @property
    def port(self):
        return self.server.port

    @property
    def broker(self):
        return self.server.broker

    # -- client factories --------------------------------------------------
    def connect(self) -> BrokerClient:
        """Return a connected BrokerClient."""
        if self.tcp:
            return BrokerClient(self.host, self.port).connect()
        server_end, client_end = socket.socketpair()
        self.server._handle_accepted(server_end, ("socketpair", 0))
        return BrokerClient().connect(sock=client_end)

    def raw_socket(self) -> socket.socket:
        """Return a connected raw socket (for protocol torture tests)."""
        if self.tcp:
            return socket.create_connection((self.host, self.port), timeout=5)
        server_end, client_end = socket.socketpair()
        self.server._handle_accepted(server_end, ("socketpair", 0))
        return client_end

    def stop(self):
        self.server.stop()


@pytest.fixture()
def server(tmp_path):
    """A running broker with a temp AOF."""
    handle = ServerHandle(aof_path=str(tmp_path / ".broker.aof"))
    yield handle
    handle.stop()


@pytest.fixture()
def server_factory(tmp_path):
    """Factory for servers with custom options (each gets its own AOF)."""
    handles = []
    counter = [0]

    def make(**kwargs):
        counter[0] += 1
        kwargs.setdefault("aof_path", str(tmp_path / ("aof-%d.log" % counter[0])))
        handle = ServerHandle(**kwargs)
        handles.append(handle)
        return handle

    yield make
    for handle in handles:
        handle.stop()


@pytest.fixture()
def client(server):
    c = server.connect()
    yield c
    c.close()


@pytest.fixture()
def client_factory(server):
    clients = []

    def make():
        c = server.connect()
        clients.append(c)
        return c

    yield make
    for c in clients:
        c.close()


def wait_for(predicate, timeout=5.0, interval=0.02):
    """Poll *predicate* until true or raise AssertionError."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    raise AssertionError("condition not met within %.1fs" % timeout)


def recv_all(client, count, timeout=5.0):
    """Receive exactly *count* messages."""
    msgs = []
    deadline = time.time() + timeout
    while len(msgs) < count:
        remaining = deadline - time.time()
        if remaining <= 0:
            raise AssertionError(
                "expected %d messages, got %d" % (count, len(msgs))
            )
        msg = client.next_message(timeout=remaining)
        assert msg is not None, "timed out waiting for messages"
        msgs.append(msg)
    return msgs
