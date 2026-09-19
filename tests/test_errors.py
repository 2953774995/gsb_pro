"""Protocol errors, illegal commands and malformed input must produce
standard ERR replies and must never crash the broker."""

import socket

import pytest

from conftest import wait_for
from minibroker.client import BrokerClient, BrokerError


def read_line(sock, timeout=5.0):
    sock.settimeout(timeout)
    data = b""
    while not data.endswith(b"\n"):
        chunk = sock.recv(4096)
        if not chunk:
            raise EOFError("server closed connection")
        data += chunk
    return data[:-1]


def test_unknown_command(server):
    raw = server.raw_socket()
    raw.sendall(b"FOOBAR\n")
    assert read_line(raw).startswith(b"ERR unknown command")
    # server is still healthy afterwards
    raw.sendall(b"PING\n")
    assert read_line(raw) == b"PONG"
    raw.close()


def test_garbage_bytes_do_not_crash(server):
    raw = server.raw_socket()
    raw.sendall(b"\x00\x01\x02\xff\xfe garbage\n")
    assert read_line(raw).startswith(b"ERR")
    raw.sendall(b"PING\n")
    assert read_line(raw) == b"PONG"
    raw.close()


def test_empty_command(server):
    raw = server.raw_socket()
    raw.sendall(b"\n")
    assert read_line(raw).startswith(b"ERR")
    raw.close()


def test_malformed_publish(server):
    raw = server.raw_socket()
    raw.sendall(b"PUBLISH onlytopic\n")
    assert read_line(raw).startswith(b"ERR malformed PUBLISH")
    raw.sendall(b"PUBLISH t notanumber\n")
    assert read_line(raw).startswith(b"ERR invalid payload length")
    raw.sendall(b"PUBLISH t -5\n")
    assert read_line(raw).startswith(b"ERR invalid payload length")
    raw.sendall(b"PING\n")
    assert read_line(raw) == b"PONG"
    raw.close()


def test_invalid_topic_rejected(server):
    raw = server.raw_socket()
    raw.sendall(b"PUBLISH bad\x01topic 1\nx")
    assert read_line(raw).startswith(b"ERR")
    raw.sendall(b"PUBLISH wild*card 1\nx")
    assert read_line(raw).startswith(b"ERR")
    # invalid subscribe patterns
    raw.sendall(b"SUBSCRIBE /*\n")
    assert read_line(raw).startswith(b"ERR")
    raw.sendall(b"SUBSCRIBE has space\n")
    assert read_line(raw).startswith(b"ERR")
    raw.sendall(b"PING\n")
    assert read_line(raw) == b"PONG"
    raw.close()


def test_oversized_header_line(server):
    raw = server.raw_socket()
    raw.sendall(b"X" * (server.server.max_command_size + 10) + b"\n")
    assert read_line(raw) == b"ERR command too large"
    # stream resynchronised: next command works
    raw.sendall(b"PING\n")
    assert read_line(raw) == b"PONG"
    raw.close()


def test_oversized_payload_rejected(server_factory):
    srv = server_factory(max_command_size=64)
    raw = srv.raw_socket()
    raw.sendall(b"PUBLISH t 100\n")  # declared payload larger than the limit
    assert read_line(raw) == b"ERR command too large"
    # connection is dropped by the server for safety
    raw.settimeout(5)
    try:
        extra = raw.recv(100)
        assert extra == b""
    except (ConnectionResetError, BrokenPipeError):
        pass
    raw.close()
    # server still serves other clients
    c = srv.connect()
    assert c.ping()
    c.close()


def test_max_command_size_enforced_for_publish(server_factory):
    srv = server_factory(max_command_size=16)
    ok_client = srv.connect()
    assert ok_client.publish("t", b"12345678")  # small payload fine
    with pytest.raises(BrokerError, match="too large"):
        ok_client.publish("t", b"x" * 100)
    ok_client.close()


def test_client_raises_broker_error_on_err(client):
    with pytest.raises(BrokerError):
        client.publish("bad topic", "x")
    with pytest.raises(BrokerError):
        client.subscribe("")
    # connection still usable
    assert client.ping()


def test_many_malformed_clients_do_not_crash(server):
    raws = [server.raw_socket() for _ in range(10)]
    for i, raw in enumerate(raws):
        raw.sendall(b"\xff\xfe BAD CMD %d \x00\n" % i)
    for raw in raws:
        assert read_line(raw).startswith(b"ERR")
        raw.close()
    c = server.connect()
    assert c.ping()
    c.close()
