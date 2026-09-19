"""Server lifecycle: graceful SHUTDOWN, BYE notification, disconnects."""

import socket
import subprocess
import sys
import time

import pytest

from conftest import TCP_AVAILABLE, wait_for
from minibroker.client import BrokerClient, BrokerClosed


def test_shutdown_notifies_clients_and_stops(server, client_factory):
    listener = client_factory()
    listener.subscribe("t")
    other = client_factory()

    other.shutdown()

    # connected clients are notified (BYE) before the server goes away
    with pytest.raises(BrokerClosed):
        while True:
            listener.next_message(timeout=5)
    wait_for(lambda: server.server.is_shutting_down, timeout=5)
    other.close()
    listener.close()


def test_next_message_timeout_returns_none(client):
    client.subscribe("nothing-here")
    assert client.next_message(timeout=0.2) is None


def test_abrupt_disconnect_cleans_subscriptions(server, client_factory):
    sub = client_factory()
    sub.subscribe("t")
    wait_for(lambda: server.broker.stats()["subscriptions"] == 1)
    # simulate a crash: the peer vanishes without any protocol goodbye
    sub._sock.shutdown(socket.SHUT_RDWR)
    sub._closed.set()
    wait_for(lambda: server.broker.stats()["subscriptions"] == 0)
    # other clients are unaffected
    c = client_factory()
    assert c.ping()


def test_server_stop_idempotent(server):
    server.stop()
    server.stop()


def test_publish_after_server_restart_same_port_unavailable_gracefully(server):
    # stopping twice / publishing after close raises a clean error
    c = server.connect()
    server.stop()
    with pytest.raises((BrokerClosed, OSError)):
        for _ in range(50):
            c.publish("t", "x")
    c.close()


@pytest.mark.skipif(not TCP_AVAILABLE, reason="TCP loopback not available in this sandbox")
def test_cli_help_runs():
    out = subprocess.run(
        [sys.executable, "-m", "minibroker.cli", "--help"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert out.returncode == 0
    assert "mb-cli" in out.stdout


def test_server_module_help_runs():
    out = subprocess.run(
        [sys.executable, "-m", "minibroker", "--help"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert out.returncode == 0
    assert "--port" in out.stdout


@pytest.mark.skipif(not TCP_AVAILABLE, reason="TCP loopback not available in this sandbox")
def test_real_tcp_end_to_end(tmp_path):
    """Explicit real-TCP smoke test (used when the sandbox allows it)."""
    from minibroker.server import BrokerServer

    srv = BrokerServer(port=0, aof_path=str(tmp_path / "aof"))
    srv.start()
    c1 = BrokerClient("127.0.0.1", srv.port).connect()
    c2 = BrokerClient("127.0.0.1", srv.port).connect()
    c1.subscribe("t")
    c2.publish("t", "over-tcp")
    msg = c1.next_message(timeout=5)
    assert msg.payload == b"over-tcp"
    c1.close()
    c2.close()
    srv.stop()
