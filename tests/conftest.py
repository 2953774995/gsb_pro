import time

import pytest

from minibroker.client import BrokerClient
from minibroker.server import BrokerServer


def collect(client, count, timeout=5.0):
    """Collect up to `count` messages, waiting at most `timeout` seconds."""
    messages = []
    deadline = time.monotonic() + timeout
    while len(messages) < count:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        message = client.next_message(timeout=remaining)
        if message is None:
            break
        messages.append(message)
    return messages


def make_server(tmp_path, **kwargs):
    kwargs.setdefault("aof_path", str(tmp_path / ".broker.aof"))
    server = BrokerServer(port=0, **kwargs)
    server.start()
    return server


@pytest.fixture
def server(tmp_path):
    srv = make_server(tmp_path)
    yield srv
    srv.stop()
    srv.wait()


@pytest.fixture
def client(server):
    cli = BrokerClient(port=server.port)
    cli.connect()
    yield cli
    cli.close()


@pytest.fixture
def client_factory(server):
    clients = []

    def make():
        cli = BrokerClient(port=server.port)
        cli.connect()
        clients.append(cli)
        return cli

    yield make
    for cli in clients:
        cli.close()
