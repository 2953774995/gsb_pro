import socket
import threading
import time

import pytest

from linebus.client import LinebusDisconnected, LinebusServerError
from tests.testutil import attach_pair
from linebus.server import LinebusServer


def recv_exact_line(sock, timeout=2):
    sock.settimeout(timeout)
    data = bytearray()
    while not data.endswith(b"\n"):
        ch = sock.recv(1)
        if not ch:
            raise AssertionError("connection closed before line was complete")
        data.extend(ch)
    return bytes(data)


def wait_condition(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.01)
    raise AssertionError("condition not reached before timeout")


def test_client_ping_publish_subscribe_and_realtime_sequence(client, make_client):
    subscriber = make_client()
    subscriber.subscribe("quality/camera-1")
    assert client.ping() == "PONG"
    sequences = [client.publish("quality/camera-1", f"event-{i}".encode()) for i in range(3)]
    assert sequences == [1, 2, 3]
    messages = [subscriber.next_message(timeout=3) for _ in range(3)]
    assert [m.payload for m in messages] == [b"event-0", b"event-1", b"event-2"]
    assert [m.sequence for m in messages] == [1, 2, 3]


def test_subscriber_receives_retained_backlog_before_new_events(client, make_client):
    client.publish("quality", b"old")
    subscriber = make_client()
    subscriber.subscribe("quality")
    old = subscriber.next_message(timeout=2)
    assert old.payload == b"old"
    client.publish("quality", b"new")
    new = subscriber.next_message(timeout=2)
    assert new.payload == b"new"
    assert new.sequence == old.sequence + 1


def test_fanout_disconnect_and_reconnect_do_not_hurt_others(client, make_client):
    alive = make_client()
    disposable = make_client()
    alive.subscribe("q")
    disposable.subscribe("q")
    client.publish("q", b"first")
    assert alive.next_message(timeout=2).payload == b"first"
    assert disposable.next_message(timeout=2).payload == b"first"
    disposable.close()
    client.publish("q", b"second")
    assert alive.next_message(timeout=2).payload == b"second"

    # A freshly reconnected client receives retained history under default N.
    reconnect = make_client()
    reconnect.subscribe("q")
    assert reconnect.next_message(timeout=2).payload == b"first"
    assert reconnect.next_message(timeout=2).payload == b"second"


def test_retention_zero_server_does_not_replay_afterwards(tmp_path):
    server = LinebusServer(
        host="127.0.0.1",
        port=0,
        retention=0,
        queue_capacity=1000,
        aof_path=str(tmp_path / "aof"),
        fsync=True,
    )
    try:
        publisher = attach_pair(server)
        publisher.publish("q", b"gone")
        subscriber = attach_pair(server)
        subscriber.subscribe("q")
        with pytest.raises(Exception):
            # queue.Empty from blocking get after a short timeout.
            subscriber.next_message(timeout=0.2)
        publisher.close()
        subscriber.close()
    finally:
        server.stop()


def test_wildcard_subscription_fanout_over_tcp(client, make_client):
    subscriber = make_client()
    subscriber.subscribe("line/*")
    client.publish("line/inspection", b"one")
    client.publish("line/inspection/camera", b"two")
    client.publish("line", b"three")
    client.publish("other", b"none")
    messages = [subscriber.next_message(timeout=2) for _ in range(3)]
    assert [m.topic for m in messages] == [
        "line/inspection",
        "line/inspection/camera",
        "line",
    ]


def test_stats_reports_subscribers_and_flush_resets_sequence(client, make_client):
    sub = make_client()
    sub.subscribe("q")
    client.publish("q", b"x")
    sub.next_message(timeout=2)
    stats = client.stats()
    assert stats["published_events"] == 1
    assert stats["subscribers"] >= 1
    assert stats["subscriptions"] >= 1
    client.flush()
    stats = client.stats()
    assert stats["published_events"] == 0
    assert stats["queued_events"] == 0
    assert client.publish("q", b"new") == 1


def test_malformed_unknown_and_invalid_topics_return_err_and_server_lives(
    raw_connection, make_client
):
    sock = raw_connection()
    sock.sendall(b"NOPE q\n")
    assert recv_exact_line(sock) == b"ERR unknown command: NOPE\n"
    sock.close()

    sock = raw_connection()
    sock.sendall(b"SUBSCRIBE bad topic\n")
    assert recv_exact_line(sock).startswith(b"ERR ")
    sock.close()

    client = make_client()
    assert client.ping() == "PONG"
    client.close()


def test_bad_payload_length_and_header_tokens_return_err(raw_connection, make_client):
    sock = raw_connection()
    sock.sendall(b"PUBLISH q bad\n")
    assert recv_exact_line(sock).startswith(b"ERR ")
    sock.close()

    sock = raw_connection()
    sock.sendall(b"SUBSCRIBE q 5\nhi")
    assert recv_exact_line(sock).startswith(b"ERR ")
    sock.close()

    client = make_client()
    assert client.ping() == "PONG"
    client.close()


def test_oversized_publish_returns_error_and_other_client_ok(make_client):
    bad = make_client()
    with pytest.raises((LinebusServerError, LinebusDisconnected)):
        bad.publish("q", b"x" * (1024 * 1024 + 1))
    bad.close()
    good = make_client()
    assert good.ping() == "PONG"
    good.close()


def test_concurrent_12_clients_no_loss_no_duplicates(tmp_path):
    server = LinebusServer(
        host="127.0.0.1",
        port=0,
        retention=5000,
        queue_capacity=0,
        aof_path=str(tmp_path / "aof"),
        fsync=False,
    )
    try:
        port = None
        subscriber_count = 6
        publisher_count = 6
        per_publisher = 25
        subscribers = []
        for _ in range(subscriber_count):
            subscriber = attach_pair(server)
            subscriber.subscribe("q")
            subscribers.append(subscriber)

        expected = list(range(1, publisher_count * per_publisher + 1))
        errors = []

        def publish(worker):
            try:
                c = attach_pair(server)
                for i in range(per_publisher):
                    value = worker * per_publisher + i + 1
                    c.publish("q", str(value).encode())
                c.close()
            except Exception as exc:  # pragma: no cover - reported below
                errors.append(exc)

        threads = [
            threading.Thread(target=publish, args=(worker,))
            for worker in range(publisher_count)
        ]
        for thread in threads:
            thread.start()

        for subscriber in subscribers:
            payloads = [int(subscriber.next_message(timeout=10).payload) for _ in expected]
            assert sorted(payloads) == expected
            assert len(payloads) == len(set(payloads))

        for thread in threads:
            thread.join(timeout=10)
            assert not thread.is_alive()
        assert not errors
        for subscriber in subscribers:
            subscriber.close()
    finally:
        server.stop()


def test_abrupt_disconnect_during_pending_events_does_not_crash(server, client):
    peer = attach_pair(server)
    peer.subscribe("slow/q")
    # Queue capacity default 1000; fill some but don't consume then disconnect.
    for i in range(10):
        client.publish("slow/q", str(i).encode())
    # Abrupt TCP half-close without closing the SDK wrapper first.
    peer._sock.shutdown(socket.SHUT_WR)
    wait_condition(lambda: client.stats()["subscribers"] == 1)
    assert client.ping() == "PONG"




def test_aof_recovery_tcp_restart(tmp_path):
    path = str(tmp_path / "restart.aof")
    first = LinebusServer(host="127.0.0.1", port=0, retention=1000, aof_path=path, fsync=True)
    try:
        publisher = attach_pair(first)
        publisher.publish("restart/q", b"persisted-1")
        publisher.publish("restart/q", b"persisted-2")
        publisher.close()
    finally:
        first.stop()

    second = LinebusServer(host="127.0.0.1", port=0, retention=1000, aof_path=path, fsync=True)
    try:
        subscriber = attach_pair(second)
        subscriber.subscribe("restart/q")
        messages = [subscriber.next_message(timeout=3) for _ in range(2)]
        assert [m.payload for m in messages] == [b"persisted-1", b"persisted-2"]
        assert [m.sequence for m in messages] == [1, 2]

        publisher = attach_pair(second)
        assert publisher.publish("restart/q", b"persisted-3") == 3
        publisher.close()
        assert subscriber.next_message(timeout=3).payload == b"persisted-3"
        subscriber.close()
    finally:
        second.stop()



def test_shutdown_notifies_connected_client(tmp_path):
    server = LinebusServer(
        host="127.0.0.1",
        port=0,
        aof_path=str(tmp_path / "aof"),
        fsync=True,
    )
    try:
        control = attach_pair(server)
        watcher = attach_pair(server)
        watcher.subscribe("q")
        thread = threading.Thread(target=control.shutdown)
        thread.start()
        with pytest.raises(LinebusDisconnected):
            # Server wakes delivery loops, notifies them, and closes sockets.
            watcher.next_message(timeout=3)
        thread.join(timeout=3)
        control.close()
        watcher.close()
        server.stop()
    finally:
        server.stop()


def test_shutdown_notifies_idle_next_message_caller(tmp_path):
    server = LinebusServer(host="127.0.0.1", port=0, aof_path=str(tmp_path / "aof"))
    try:
        control = attach_pair(server)
        idle = attach_pair(server)
        thread = threading.Thread(target=control.shutdown)
        thread.start()
        with pytest.raises(LinebusDisconnected, match="shutting down"):
            idle.next_message(timeout=3)
        thread.join(timeout=3)
        control.close()
        idle.close()
        server.stop()
    finally:
        server.stop()
