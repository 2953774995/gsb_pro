import socket

import pytest

from linebus.client import LinebusClient
from linebus.server import LinebusServer


@pytest.fixture()
def tmp_aof(tmp_path):
    return str(tmp_path / "linebus.aof")


@pytest.fixture()
def server(tmp_aof):
    """A running broker/network service backed by connected socket pairs.

    The production code uses ordinary TCP sockets; the pairs exercise the same
    makefile/sendall/close code paths while also working in sandboxes that do
    not permit binding an AF_INET listener.
    """
    server = LinebusServer(
        host="127.0.0.1",
        port=0,
        retention=1000,
        queue_capacity=1000,
        queue_full_policy="block",
        aof_path=tmp_aof,
        fsync=True,
    )
    # Initialise broker/state but don't require permission to bind a port.
    with server._state_lock:
        server._next_connection_id = 1
    yield server
    server.stop()


@pytest.fixture()
def make_client(server):
    created = []

    def attach_client(timeout=None):
        client_sock, sdk_sock = socket.socketpair()
        client_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server._spawn_connection(client_sock, ("socketpair", len(created)))
        client = LinebusClient("127.0.0.1", server.port, timeout=timeout)
        client.attach_socket(sdk_sock)
        created.append(client)
        return client

    yield attach_client

    for client in created:
        client.close()


@pytest.fixture()
def raw_connection(server):
    created = []

    def connect():
        server_sock, raw_sock = socket.socketpair()
        server._spawn_connection(server_sock, ("socketpair", len(created)))
        created.append(raw_sock)
        return raw_sock

    yield connect

    for sock in created:
        try:
            sock.close()
        except OSError:
            pass


@pytest.fixture()
def client(make_client):
    return make_client()
