import socket
import threading
import time

import pytest

from minibroker import protocol
from minibroker.client import BrokerClient, ServerError
from tests.conftest import open_raw_socket, read_one_reply, raw_command, wait_for


@pytest.fixture
def client(start_server):
    server = start_server()

    def factory():
        return BrokerClient(port=server.actual_port, timeout=3).connect()

    return server, factory


def test_ping_and_stats_over_tcp(client):
    server, make_client = client
    with make_client() as c:
        assert c.ping() == b"PONG"
        stats = c.stats()
        assert stats["connections"] >= 1
        assert stats["next_sequence"] == 1
        assert stats["retention_limit"] == 1000


def test_subscribe_after_publish_gets_retained_backlog(start_server):
    server = start_server(retention=10)
    publisher = BrokerClient(port=server.actual_port).connect()
    assert publisher.publish("t", b"before") == 1
    publisher.close()

    subscriber = BrokerClient(port=server.actual_port).connect()
    subscriber.subscribe("t")
    message = subscriber.next_message(2)
    assert message == message.__class__(1, b"t", b"before")
    subscriber.close()


def test_realtime_publish_subscribe_sequence_increases(client):
    server, make_client = client
    subscriber = make_client()
    publisher = make_client()
    subscriber.subscribe("realtime")
    time.sleep(0.05)
    assert publisher.publish("realtime", b"hello world") == 1
    first = subscriber.next_message(2)
    assert first.topic == b"realtime"
    assert first.payload == b"hello world"
    assert first.sequence == 1
    assert publisher.publish("realtime", b"second") == 2
    second = subscriber.next_message(2)
    assert second.sequence == 2
    subscriber.close()
    publisher.close()


def test_multi_subscriber_fanout_no_loss_or_duplicate(start_server):
    server = start_server()
    subscribers = []
    for _ in range(10):
        c = BrokerClient(port=server.actual_port).connect()
        c.subscribe("parallel")
        subscribers.append(c)
    publishers = [BrokerClient(port=server.actual_port).connect() for _ in range(3)]

    # Wait until all 10 subscribers are registered before publishing.
    deadline = time.time() + 3
    while time.time() < deadline:
        stats = publishers[0].stats()
        if stats["subscriptions"] == 10:
            break
        time.sleep(0.02)
    assert publishers[0].stats()["subscriptions"] == 10

    messages_per_publisher = 20
    barrier = threading.Barrier(len(publishers))

    def publish_many(publisher, publisher_id):
        barrier.wait(3)
        for idx in range(messages_per_publisher):
            publisher.publish("parallel", f"p{publisher_id}-{idx}".encode())

    threads = [
        threading.Thread(target=publish_many, args=(publisher, idx))
        for idx, publisher in enumerate(publishers)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)
    assert all(not thread.is_alive() for thread in threads)

    expected_total = len(publishers) * messages_per_publisher
    for subscriber in subscribers:
        received = []
        for _ in range(expected_total):
            received.append(subscriber.next_message(5).sequence)
        assert sorted(received) == list(range(1, expected_total + 1))
        assert len(set(received)) == expected_total

    for c in subscribers + publishers:
        c.close()


def test_disconnected_subscriber_does_not_affect_others(start_server):
    server = start_server()
    raw_other = raw_command(server, b"SUBSCRIBE", b"alive")
    # Read SUBSCRIBED reply.
    assert read_one_reply(raw_other) == b"SUBSCRIBED"

    leaving = BrokerClient(port=server.actual_port).connect()
    leaving.subscribe("disconnect")
    leaving.close()

    # The closed subscriber's routing state is removed promptly and cannot
    # receive later messages.  In the socketpair test transport, reaping the
    # reader thread can lag slightly, so assert routing semantics rather than
    # the internal thread-list size.
    with BrokerClient(port=server.actual_port).connect() as admin:
        assert wait_for(lambda: admin.stats()["subscriptions"] == 1, 3)

    publisher = BrokerClient(port=server.actual_port).connect()
    assert publisher.publish("alive", b"works") == 1
    assert read_one_reply(raw_other) == [b"PUB", b"1", b"alive", b"works"]
    publisher.close()
    raw_other.close()


def test_retention_zero_tcp_server(start_server):
    server = start_server(retention=0)
    publisher = BrokerClient(port=server.actual_port).connect()
    publisher.publish("drop", b"gone")
    subscriber = BrokerClient(port=server.actual_port).connect()
    subscriber.subscribe("drop")
    time.sleep(0.05)
    publisher.publish("drop", b"kept")
    message = subscriber.next_message(2)
    assert message.payload == b"kept"
    publisher.close()
    subscriber.close()


def test_wildcard_tcp_subscription(start_server):
    server = start_server()
    subscriber = BrokerClient(port=server.actual_port).connect()
    publisher = BrokerClient(port=server.actual_port).connect()
    subscriber.subscribe("news/*")
    time.sleep(0.05)
    publisher.publish("news/tech", b"phone")
    publisher.publish("weather", b"sun")
    first = subscriber.next_message(2)
    assert first.topic == b"news/tech"
    assert first.payload == b"phone"
    with pytest.raises(TimeoutError):
        subscriber.next_message(0.2)
    subscriber.close()
    publisher.close()


def test_unknown_command_returns_error(client):
    server, make_client = client
    with make_client() as c:
        with pytest.raises(ServerError, match="unknown command"):
            c._request("BOGUS")


def test_invalid_topic_and_arity_return_standard_errors(client):
    server, make_client = client
    with make_client() as c:
        with pytest.raises(ServerError):
            c.publish("bad\ntopic", b"x")
        with pytest.raises(ServerError):
            c.subscribe("")
        with pytest.raises(ServerError):
            c._request("PUBLISH", b"only-topic")
        with pytest.raises(ServerError):
            c.ping and c._request("PING", b"extra")


def test_malformed_protocol_does_not_stop_server(start_server):
    server = start_server()
    bad = open_raw_socket(server)
    bad.sendall(b"this is not a frame\n")
    bad.settimeout(3)
    assert read_one_reply(bad).startswith(b"ERR protocol error")
    bad.close()

    incomplete = open_raw_socket(server)
    incomplete.sendall(b"*1\r\n$3\r\nab\r\n")
    incomplete.settimeout(3)
    incomplete.close()

    with BrokerClient(port=server.actual_port).connect() as healthy:
        assert healthy.ping() == b"PONG"


def test_command_size_limit_returns_error_then_connection_closes(start_server):
    server = start_server()
    sock = open_raw_socket(server)
    payload = b"x" * (1024 * 1024)
    sock.sendall(protocol.encode_frame([b"PUBLISH", b"t", payload]))
    sock.settimeout(3)
    reply = read_one_reply(sock)
    assert reply.startswith(b"ERR protocol error")
    assert b"maximum size" in reply
    sock.close()

    with BrokerClient(port=server.actual_port).connect() as healthy:
        assert healthy.ping() == b"PONG"


def test_flush_over_tcp(start_server):
    server = start_server()
    publisher = BrokerClient(port=server.actual_port).connect()
    publisher.publish("t", b"old")
    publisher.flush()
    subscriber = BrokerClient(port=server.actual_port).connect()
    subscriber.subscribe("t")
    time.sleep(0.05)
    sequence = publisher.publish("t", b"new")
    assert sequence == 1
    assert subscriber.next_message(2).payload == b"new"
    publisher.close()
    subscriber.close()


def test_graceful_shutdown_notifies_client(start_server, tmp_path):
    server = start_server(aof_path=str(tmp_path / "shutdown.aof"))
    client = BrokerClient(port=server.actual_port).connect()
    assert client.ping() == b"PONG"
    client.shutdown()
    assert server.completed_event.wait(5)
    assert client.server_shutdown.is_set()


def test_aof_restart_restores_retained_messages_and_sequence(start_server, tmp_path):
    path = str(tmp_path / "restart.aof")
    first = start_server(aof_path=path)
    publisher = BrokerClient(port=first.actual_port).connect()
    publisher.publish("persisted", b"one")
    publisher.publish("persisted", b"two")
    publisher.close()
    first.stop()

    second = start_server(aof_path=path)
    subscriber = BrokerClient(port=second.actual_port).connect()
    subscriber.subscribe("persisted")
    first_message = subscriber.next_message(2)
    second_message = subscriber.next_message(2)
    assert (first_message.sequence, first_message.payload) == (1, b"one")
    assert (second_message.sequence, second_message.payload) == (2, b"two")

    publisher = BrokerClient(port=second.actual_port).connect()
    assert publisher.publish("persisted", b"three") == 3
    assert subscriber.next_message(2).payload == b"three"
    subscriber.close()
    publisher.close()
