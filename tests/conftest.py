import os
import socket
import threading

import pytest

from linebus.broker import Broker
from linebus.server import LinebusServer


class PairedServer:
    """Production server sessions backed by connected socket pairs.

    The development sandbox forbids TCP/AF_UNIX bind/connect, but permits
    socketpair. Each factory call creates a separate production
    ClientSession; this still exercises parser, broker, I/O threads, and SDK.
    """

    def __init__(self, tmp_path, **kwargs):
        self.aof_path = str(tmp_path / "linebus.aof")
        self.server = LinebusServer(
            host="127.0.0.1",
            port=0,
            aof_path=self.aof_path,
            **kwargs,
        )

    def _new_pair(self):
        server_sock, client_sock = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        session = self.server.attach_socket(server_sock, ("pair", 0))
        if session is None:
            server_sock.close()
            client_sock.close()
            raise RuntimeError("server is shutting down")
        session.start()
        return client_sock

    def attach_client(self):
        from linebus.client import LinebusClient

        client = LinebusClient()
        client._attach_socket(self._new_pair())  # noqa: SLF001: test harness hook
        return client

    def raw_client(self):
        sock = self._new_pair()
        sock.settimeout(5.0)
        return sock

    def shutdown(self):
        self.server.request_shutdown()
        self.server.wait_closed(timeout=2.0)


@pytest.fixture
def paired_server(tmp_path):
    ps = PairedServer(tmp_path)
    try:
        yield ps
    finally:
        ps.shutdown()


@pytest.fixture
def make_paired_server(tmp_path):
    instances = []

    def factory(**kwargs):
        ps = PairedServer(tmp_path, **kwargs)
        instances.append(ps)
        return ps

    yield factory
    for ps in instances:
        ps.shutdown()


@pytest.fixture
def broker(tmp_path):
    from linebus.aof import AppendOnlyLog

    aof = AppendOnlyLog(str(tmp_path / "broker.aof"))
    aof.initialize()
    b = Broker(aof)
    try:
        yield b
    finally:
        aof.close()


def recv_line(sock):
    data = bytearray()
    while not data.endswith(b"\n"):
        chunk = sock.recv(1)
        if not chunk:
            raise ConnectionError("closed before line")
        data.extend(chunk)
    return bytes(data[:-1])


def read_event(sock):
    header = recv_line(sock)
    command, seq_b, topic_b, length_b = header.split(b" ", 3)
    assert command == b"EVENT"
    payload = recv_exact(sock, int(length_b))
    terminator = recv_exact(sock, 1)
    assert terminator == b"\n"
    return int(seq_b), topic_b.decode(), payload


def recv_exact(sock, length):
    chunks = []
    remaining = length
    while remaining:
        chunk = sock.recv(remaining)
        if not chunk:
            raise ConnectionError("closed during payload")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)
