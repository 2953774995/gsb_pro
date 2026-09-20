import socket
import threading

import pytest

from linebus.client import LinebusClient, LinebusConnectionError, LinebusError, LinebusTimeout
from linebus.protocol import encode_command, encode_publish

from .conftest import read_event, recv_line


def test_sdk_ping_publish_subscribe(paired_server):
    client = paired_server.attach_client()
    assert client.ping() == "OK PONG"
    client.subscribe("camera line/1")
    sequence = client.publish("camera line/1", b"photo\n\t\x00")
    event = client.next_message(timeout=2)
    assert sequence == event.sequence == 1
    assert event.topic == "camera line/1"
    assert event.payload == b"photo\n\t\x00"
    client.unsubscribe("cam/1")
    client.close()


def test_publish_before_subscribe_uses_retention(paired_server):
    publisher = paired_server.attach_client()
    publisher.publish("cam/1", b"before")
    subscriber = paired_server.attach_client()
    subscriber.subscribe("cam/1")
    event = subscriber.next_message(timeout=2)
    assert event.sequence == 1
    assert event.payload == b"before"
    publisher.close()
    subscriber.close()


def test_multiple_sdk_subscribers_fan_out(paired_server):
    publisher = paired_server.attach_client()
    clients = [paired_server.attach_client() for _ in range(3)]
    for client in clients:
        client.subscribe("cam/1")
    seq = publisher.publish("cam/1", b"fan")
    received = [client.next_message(timeout=2) for client in clients]
    assert [event.sequence for event in received] == [seq] * 3
    assert [event.payload for event in received] == [b"fan"] * 3
    publisher.close()
    for client in clients:
        client.close()


def test_wildcard_subscription(paired_server):
    publisher = paired_server.attach_client()
    subscriber = paired_server.attach_client()
    subscriber.subscribe("cam/*")
    publisher.publish("cam/a", b"A")
    publisher.publish("cam/b", b"B")
    publisher.publish("other/c", b"C")
    first = subscriber.next_message(1)
    second = subscriber.next_message(1)
    assert (first.topic, first.payload) == ("cam/a", b"A")
    assert (second.topic, second.payload) == ("cam/b", b"B")
    with pytest.raises(LinebusTimeout):
        subscriber.next_message(timeout=0.1)
    publisher.close()
    subscriber.close()


def test_retention_zero_server(make_paired_server):
    ps = make_paired_server(retention=0)
    publisher = ps.attach_client()
    publisher.publish("x", b"lost")
    subscriber = ps.attach_client()
    subscriber.subscribe("x")
    with pytest.raises(LinebusTimeout):
        subscriber.next_message(timeout=0.1)
    publisher.publish("x", b"live")
    event = subscriber.next_message(1)
    assert event.payload == b"live"
    publisher.close()
    subscriber.close()


def test_stats(paired_server):
    client = paired_server.attach_client()
    client.subscribe("x")
    client.publish("x", b"v")
    stats = client.stats()
    assert stats["connections"] >= 1
    assert stats["last_sequence"] == 1
    assert stats["retention"] == 1000
    assert stats["queue_capacity"] == 1000
    client.close()


def test_flush_clears_queued_and_retained_events(paired_server):
    c1 = paired_server.attach_client()
    c2 = paired_server.attach_client()
    c1.subscribe("x")
    c2.publish("x", b"old")
    # Wait for c1 to receive once, then flush later event retained for future.
    assert c1.next_message(1).payload == b"old"
    c1.unsubscribe("x")
    c2.publish("x", b"retained-before-flush")
    c2.flush()
    c3 = paired_server.attach_client()
    c1.subscribe("x")
    c3.subscribe("x")
    with pytest.raises(LinebusTimeout):
        c3.next_message(timeout=0.1)
    seq = c2.publish("x", b"new")
    event = c1.next_message(1)
    event3 = c3.next_message(1)
    assert seq == event.sequence == event3.sequence == 1
    for c in (c1, c2, c3):
        c.close()


def test_invalid_topics_return_err_and_continue(paired_server):
    client = paired_server.attach_client()
    for topic in ["", "a\x00b", " leading", "trailing "]:
        with pytest.raises(LinebusError):
            client.publish(topic, b"x")
    assert client.ping() == "OK PONG"
    client.close()


def test_unknown_command_and_protocol_error(paired_server):
    sock = paired_server.raw_client()
    sock.sendall(b"WHAT\n")
    assert recv_line(sock).startswith(b"ERR unknown command")
    sock.sendall(b"PUBLISH a 1\nXY")  # wrong payload terminator
    assert recv_line(sock).startswith(b"ERR payload must be terminated")
    with pytest.raises(ConnectionError):
        recv_line(sock)
    sock.close()


def test_oversized_command_returns_err_and_closes(paired_server):
    sock = paired_server.raw_client()
    sock.sendall(b"PUBLISH a 1048577\n")
    reply = recv_line(sock)
    assert reply.startswith(b"ERR payload exceeds maximum size")
    with pytest.raises(ConnectionError):
        recv_line(sock)
    sock.close()


def test_raw_commands_and_event_protocol(paired_server):
    sub = paired_server.raw_client()
    pub = paired_server.raw_client()
    sub.sendall(encode_command("SUBSCRIBE", "raw"))
    assert recv_line(sub) == b"OK SUBSCRIBED raw"
    pub.sendall(encode_publish("raw", b"line\nmore"))
    assert recv_line(pub) == b"OK SEQ 1"
    assert read_event(sub) == (1, "raw", b"line\nmore")
    sub.close()
    pub.close()


def test_disconnect_does_not_affect_other_subscribers(paired_server):
    fragile = paired_server.attach_client()
    healthy = paired_server.attach_client()
    publisher = paired_server.attach_client()
    fragile.subscribe("x")
    healthy.subscribe("x")
    fragile.close()
    sequence = publisher.publish("x", b"ok")
    event = healthy.next_message(2)
    assert event.sequence == sequence
    assert event.payload == b"ok"
    healthy.close()
    publisher.close()


def test_disconnected_events_remain_available_for_reconnect(paired_server):
    first = paired_server.attach_client()
    first.publish("x", b"durable")
    first.close()
    second = paired_server.attach_client()
    second.subscribe("x")
    event = second.next_message(2)
    assert (event.sequence, event.payload) == (1, b"durable")
    second.close()


def test_shutdown_notifies_connected_clients(paired_server):
    client = paired_server.attach_client()
    client.subscribe("x")
    paired_server.server.request_shutdown()
    with pytest.raises(LinebusConnectionError):
        client.ping()
    client.close()


def test_concurrent_12_clients_no_loss_or_duplicates(paired_server):
    subscribers = [paired_server.attach_client() for _ in range(6)]
    publishers = [paired_server.attach_client() for _ in range(6)]
    for subscriber in subscribers:
        subscriber.subscribe("inspection/*")

    per_publisher = 20
    barrier = threading.Barrier(len(publishers))
    errors = []

    def publish(client, index):
        try:
            barrier.wait(5)
            for i in range(per_publisher):
                client.publish(f"inspection/p{index}", f"{index}-{i}".encode())
        except Exception as exc:  # pragma: no cover - reports test failure
            errors.append(exc)

    threads = [
        threading.Thread(target=publish, args=(client, index))
        for index, client in enumerate(publishers)
    ]
    for thread in threads:
        thread.start()
    expected = len(publishers) * per_publisher
    for subscriber in subscribers:
        sequences = [subscriber.next_message(timeout=10).sequence for _ in range(expected)]
        assert len(sequences) == expected
        assert len(sequences) == len(set(sequences))
        assert sorted(sequences) == list(range(1, expected + 1))
    for thread in threads:
        thread.join(5)
    assert not errors
    for client in publishers + subscribers:
        client.close()
