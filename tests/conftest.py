"""Shared pytest fixtures.

The suite talks to the broker over *real* sockets using exactly the same
reader/writer threads and wire protocol as production:

* when the platform allows listening on TCP (normal CI / dev machines), the
  harness binds 127.0.0.1:0 and the client connects over loopback;
* in sandboxes that forbid ``bind``/``connect`` it transparently falls back to
  a connected ``socket.socketpair`` (per connection), so behaviour coverage is
  identical apart from the kernel's TCP stack itself.
"""

from __future__ import annotations

import os
import socket
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from minibroker.broker import Broker  # noqa: E402
from minibroker.client import BrokerClient  # noqa: E402
from minibroker.protocol import ReplyReader, encode_command  # noqa: E402
from minibroker.server import BrokerServer  # noqa: E402


def tcp_available() -> bool:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", 0))
    except OSError:
        return False
    else:
        return True
    finally:
        probe.close()


TCP_AVAILABLE = tcp_available()
requires_tcp = pytest.mark.skipif(
    not TCP_AVAILABLE, reason="sandbox forbids TCP bind/connect"
)


@pytest.fixture
def aof_path(tmp_path):
    return str(tmp_path / ".broker.aof")


class RawClient:
    """Minimal raw-protocol client (no background thread)."""

    def __init__(self, sock: socket.socket) -> None:
        self.sock = sock
        self.stream = sock.makefile("rb")
        self.reader = ReplyReader(self.stream)

    def send(self, frame: bytes) -> None:
        self.sock.sendall(frame)

    def command(self, name: str, *args, payload: bytes = b""):
        self.send(encode_command(name, *args, payload=payload if name == "PUBLISH" else None))
        return self.read_reply()

    def read_reply(self):
        return self.reader.read_reply()

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


class BrokerHarness:
    """A started broker plus convenient client factories."""

    def __init__(self, aof_path, retain=1000, queue_size=10000,
                 overflow="drop-oldest", block_timeout=5.0, fsync=False):
        self.aof_path = aof_path
        self.tcp = TCP_AVAILABLE
        self.kwargs = dict(
            aof_path=aof_path,
            retain=retain,
            queue_size=queue_size,
            overflow=overflow,
            block_timeout=block_timeout,
            fsync=fsync,
        )
        self.server = BrokerServer(host="127.0.0.1", port=0, **self.kwargs)
        if self.tcp:
            self.port = self.server.start()
        else:
            self.server.start_broker()

    # ------------------------------------------------------------------ #
    def _make_sockets(self, small_rcvbuf=False):
        if self.tcp:
            sock = socket.create_connection(("127.0.0.1", self.port), timeout=5)
            server_sock = None
        else:
            server_sock, sock = socket.socketpair()
            if small_rcvbuf:
                for s in (server_sock, sock):
                    try:
                        s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024)
                    except OSError:
                        pass
        return server_sock, sock

    def client(self, on_message=None, small_rcvbuf=False) -> BrokerClient:
        server_sock, sock = self._make_sockets(small_rcvbuf=small_rcvbuf)
        if server_sock is not None:
            self.server.run_connection(server_sock, peer="pair")
        client = BrokerClient(timeout=5, on_message=on_message)
        client.adopt_socket(sock)
        return client

    def raw_client(self, small_rcvbuf=False) -> RawClient:
        server_sock, sock = self._make_sockets(small_rcvbuf=small_rcvbuf)
        if server_sock is not None:
            self.server.run_connection(server_sock, peer="pair")
        return RawClient(sock)

    def attach_socket(self, server_sock, sock) -> None:
        if not self.tcp:
            self.server.run_connection(server_sock, peer="pair")

    # ------------------------------------------------------------------ #
    def stop(self) -> None:
        self.server.stop(timeout=10)

    def restart(self, **overrides) -> "BrokerHarness":
        self.stop()
        kwargs = dict(self.kwargs)
        kwargs.update(overrides)
        new = BrokerHarness.__new__(BrokerHarness)
        new.aof_path = self.aof_path
        new.tcp = self.tcp
        new.kwargs = kwargs
        new.server = BrokerServer(host="127.0.0.1", port=0, **kwargs)
        new.port = new.server.start() if new.tcp else None
        if not new.tcp:
            new.server.start_broker()
        return new


@pytest.fixture
def harness(aof_path):
    h = BrokerHarness(aof_path)
    yield h
    h.stop()


def drain(client, count, timeout=5.0):
    """Receive exactly ``count`` messages, asserting none time out."""
    out = []
    for _ in range(count):
        msg = client.next_message(timeout=timeout)
        assert msg is not None, "timed out waiting for message"
        out.append(msg)
    return out


def wait_until(predicate, timeout=5.0, interval=0.01):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False
