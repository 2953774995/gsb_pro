import socket

import pytest

from minibroker import protocol
from minibroker.broker import Broker
from minibroker.server import BrokerServer, Connection


@pytest.fixture
def network_pair(tmp_path):
    broker = Broker(str(tmp_path / "network.aof"), retention=10)
    server = BrokerServer(broker=broker)
    pairs = []

    def connect():
        client_sock, server_sock = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        client_sock.settimeout(3)
        conn = Connection(server_sock, ("socketpair", 0), broker, server)
        server._connections.append(conn)
        conn.start()
        pairs.append((client_sock, conn))
        return client_sock

    yield broker, connect

    for client_sock, conn in pairs:
        conn.close()
        client_sock.close()
    broker.close()


def request(sock, *parts):
    sock.sendall(protocol.encode_frame(list(parts)))
    return protocol.read_value(sock.makefile("rb", buffering=0))


def test_connection_ping_stats_publish_subscribe(network_pair):
    broker, connect = network_pair
    subscriber = connect()
    publisher = connect()

    assert request(subscriber, b"PING") == b"PONG"
    assert request(subscriber, b"SUBSCRIBE", b"topic") == b"SUBSCRIBED"
    assert request(publisher, b"PUBLISH", b"topic", b"binary\r\n\t\x00") == 1
    assert protocol.read_value(subscriber.makefile("rb", buffering=0)) == [
        b"PUB", b"1", b"topic", b"binary\r\n\t\x00"
    ]
    assert request(subscriber, b"STATS") == [
        b"STATS",
        b"topics", b"1",
        b"retained_messages", b"1",
        b"subscriptions", b"1",
        b"connections", b"2",
        b"pending_messages", b"0",
        b"next_sequence", b"2",
        b"published_total", b"1",
        b"retention_limit", b"10",
        b"max_client_queue", b"0",
    ]


def test_connection_fanout_and_unsubscribe(network_pair):
    _broker, connect = network_pair
    first = connect()
    second = connect()
    publisher = connect()
    assert request(first, b"SUBSCRIBE", b"shared") == b"SUBSCRIBED"
    assert request(second, b"SUBSCRIBE", b"shared") == b"SUBSCRIBED"
    assert request(publisher, b"PUBLISH", b"shared", b"x") == 1
    for sock in (first, second):
        assert protocol.read_value(sock.makefile("rb", buffering=0)) == [
            b"PUB", b"1", b"shared", b"x"
        ]
    assert request(first, b"UNSUBSCRIBE", b"shared") == b"UNSUBSCRIBED"
    assert request(first, b"UNSUBSCRIBE", b"shared") == b"NOT_SUBSCRIBED"
    assert request(publisher, b"PUBLISH", b"shared", b"y") == 2
    assert protocol.read_value(second.makefile("rb", buffering=0)) == [
        b"PUB", b"2", b"shared", b"y"
    ]


def test_connection_protocol_and_command_errors(network_pair):
    _broker, connect = network_pair
    sock = connect()
    sock.sendall(b"garbage\r\n")
    reply = protocol.read_value(sock.makefile("rb", buffering=0))
    assert reply.startswith(b"ERR protocol error")
    # The malformed connection is closed.
    assert sock.recv(1) == b""

    healthy = connect()
    assert request(healthy, b"BOGUS") == b"ERR unknown command 'BOGUS'"
    assert request(healthy, b"PUBLISH", b"bad\ntopic", b"x").startswith(b"ERR ")
    assert request(healthy, b"SUBSCRIBE").startswith(b"ERR ")
    assert request(healthy, b"PING") == b"PONG"


def test_connection_oversize_frame_error(network_pair):
    _broker, connect = network_pair
    sock = connect()
    frame = protocol.encode_frame([b"PUBLISH", b"t", b"x" * (1024 * 1024)])
    sock.sendall(frame)
    reply = protocol.read_value(sock.makefile("rb", buffering=0))
    assert reply.startswith(b"ERR protocol error")
    assert b"maximum size" in reply


def test_connection_flush_and_graceful_shutdown_notice(network_pair):
    broker, connect = network_pair
    sock = connect()
    publisher = connect()
    assert request(sock, b"SUBSCRIBE", b"t") == b"SUBSCRIBED"
    assert request(publisher, b"PUBLISH", b"t", b"old") == 1
    # Consume first push so the queue is empty before flush.
    assert protocol.read_value(sock.makefile("rb", buffering=0))[3] == b"old"
    assert request(publisher, b"FLUSH") == b"FLUSHED"
    assert broker.stats()["next_sequence"] == 1

    assert request(sock, b"SHUTDOWN") == b"BYE"
    # The standalone BrokerServer fixture has no listener, but its shutdown
    # helper still sends the asynchronous notice after queued messages.
    assert protocol.read_value(sock.makefile("rb", buffering=0)) == [b"SHUTDOWN"]
