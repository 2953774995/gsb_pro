import os
import socket
import sys
import threading
import time
from collections import deque
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from minibroker import protocol  # noqa: E402
from minibroker.broker import Broker  # noqa: E402
from minibroker.messages import StoredMessage  # noqa: E402
from minibroker.server import BrokerServer  # noqa: E402


class FakeConnection:
    """Minimal connection duck-type used to test Broker routing without TCP."""

    def __init__(self):
        self.id = 0
        self.subscriptions = {}
        self._queue = deque()
        self._delivered = set()
        self._lock = threading.Lock()

    def enqueue_message(self, subscription_ids, message):
        with self._lock:
            self._queue.append((tuple(subscription_ids), message))

    def pending_count(self):
        with self._lock:
            return len(self._queue)

    def has_seen_sequence(self, sequence):
        with self._lock:
            return sequence in self._delivered or any(
                message.sequence == sequence for _ids, message in self._queue
            )

    def pop(self):
        with self._lock:
            item = self._queue.popleft()[1]
            self._delivered.add(item.sequence)
            return item

    def pop_all(self):
        with self._lock:
            values = [item[1] for item in self._queue]
            self._delivered.update(item.sequence for item in values)
            self._queue.clear()
            return values

    def remove_pending_subscription(self, subscription_id):
        with self._lock:
            kept = deque()
            for ids, message in self._queue:
                remaining = tuple(item for item in ids if item != subscription_id)
                if remaining:
                    kept.append((remaining, message))
            self._queue = kept

    def clear_pending(self):
        with self._lock:
            self._queue.clear()
            self._delivered.clear()


@pytest.fixture
def fake_connection_factory():
    created = []

    def factory(broker):
        conn = FakeConnection()
        broker.register_connection(conn)
        created.append(conn)
        return conn

    return factory


@pytest.fixture
def make_broker(tmp_path):
    brokers = []

    def factory(path=None, **kwargs):
        if path is None:
            path = tmp_path / f"broker-{len(brokers)}.aof"
        broker = Broker(str(path), **kwargs)
        brokers.append(broker)
        return broker, path

    yield factory
    for broker in brokers:
        broker.close()


def _socketpair_server(broker, **kwargs):
    """Create a BrokerServer whose accept loop is fed by socket.socketpair.

    This is a test fallback for sandboxes that deny both TCP bind and AF_UNIX
    bind.  It uses the production accept loop and Connection implementation;
    only the listener transport changes.
    """

    server = BrokerServer(
        broker=broker,
        max_frame_size=kwargs.get("max_frame_size", protocol.DEFAULT_MAX_FRAME_SIZE),
    )
    server.injected_accepts = []
    def new_client_socket(timeout=3):
        client_sock, server_sock = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        client_sock.settimeout(timeout)
        server.inject_accepted_socket(server_sock)
        return client_sock

    def connect_socketpair(_address=None, timeout=None, *_args, **_kwargs):
        return new_client_socket(timeout)

    server.start()
    server._test_socketpair_helper = new_client_socket
    return server, connect_socketpair, new_client_socket


@pytest.fixture
def start_server(tmp_path, monkeypatch):
    servers = []
    connectors = []

    def factory(**kwargs):
        index = len(servers)
        path = kwargs.pop("aof_path", str(tmp_path / f"server-{index}.aof"))
        server = BrokerServer(port=0, aof_path=path, **kwargs)
        connector = None
        pair_before_connect = None
        try:
            server.start()
        except (PermissionError, OSError) as tcp_exc:
            # Some CI/sandbox profiles deny listener bind().  Fall back to
            # pre-connected socketpairs instead of skipping network tests.
            server, connector, pair_before_connect = _socketpair_server(
                server.broker, **kwargs
            )
            monkeypatch.setattr(socket, "create_connection", connector)
        servers.append(server)
        connectors.append((connector, pair_before_connect))
        return server

    yield factory
    for server in servers:
        server.stop()


def open_raw_socket(server):
    helper = getattr(server, "_test_socketpair_helper", None)
    if helper is not None:
        return helper()
    return socket.create_connection(("127.0.0.1", server.actual_port), timeout=3)


_live_raw_sockets = []


def raw_command(server, *parts):
    sock = open_raw_socket(server)
    sock.sendall(protocol.encode_frame(list(parts)))
    _live_raw_sockets.append(sock)
    return sock


class SocketProtocolReader:
    """Small readline/exact-read adapter that never owns/closes the socket."""

    def __init__(self, sock):
        self.sock = sock

    def read(self, size):
        chunks = []
        remaining = size
        while remaining:
            chunk = self.sock.recv(remaining)
            if not chunk:
                raise EOFError("connection closed")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def readline(self, limit=-1):
        chunks = []
        count = 0
        while limit < 0 or count < limit:
            byte = self.sock.recv(1)
            if not byte:
                break
            chunks.append(byte)
            count += 1
            if byte == b"\n":
                break
        return b"".join(chunks)


def read_one_reply(sock):
    # Each call reads one complete reply, so a stateless adapter is sufficient.
    return protocol.read_value(SocketProtocolReader(sock))


def wait_for(predicate, timeout=3.0, interval=0.02):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


@pytest.fixture
def stored_message():
    return StoredMessage
