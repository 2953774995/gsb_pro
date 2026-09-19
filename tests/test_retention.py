"""Retention (no-subscriber) and subscriber-overflow queue semantics."""

import socket

import pytest

from minibroker.errors import ServerError
from tests.conftest import BrokerHarness, RawClient, drain, wait_until


def test_message_before_subscribe_is_replayed_by_default(aof_path):
    h = BrokerHarness(aof_path)
    try:
        pub = h.client()
        pub.publish("late", b"past-1")
        pub.publish("late", b"past-2")
        sub = h.client()
        sub.subscribe("late")
        msgs = drain(sub, 2)
        assert [m[2] for m in msgs] == [b"past-1", b"past-2"]
    finally:
        h.stop()


def test_backlog_replay_precedes_live_messages(aof_path):
    h = BrokerHarness(aof_path)
    try:
        pub = h.client()
        pub.publish("t", b"old")
        sub = h.client()
        sub.subscribe("t")
        assert sub.next_message(2)[2] == b"old"
        pub.publish("t", b"new")
        assert sub.next_message(2)[2] == b"new"
    finally:
        h.stop()


def test_retain_zero_drops_without_subscribers(aof_path):
    h = BrokerHarness(aof_path, retain=0)
    try:
        pub = h.client()
        pub.publish("t", b"dropped")
        sub = h.client()
        sub.subscribe("t")
        assert sub.next_message(timeout=0.3) is None
        pub.publish("t", b"live")
        assert sub.next_message(2)[2] == b"live"
    finally:
        h.stop()


def test_retained_history_is_bounded_per_topic(aof_path):
    h = BrokerHarness(aof_path, retain=3)
    try:
        pub = h.client()
        for i in range(10):
            pub.publish("t", b"m%d" % i)
        sub = h.client()
        sub.subscribe("t")
        msgs = drain(sub, 3)
        assert [m[2] for m in msgs] == [b"m7", b"m8", b"m9"]
        assert sub.next_message(timeout=0.2) is None
    finally:
        h.stop()


def test_retained_history_is_separate_per_topic(aof_path):
    h = BrokerHarness(aof_path, retain=2)
    try:
        pub = h.client()
        for i in range(5):
            pub.publish("a", b"a%d" % i)
            pub.publish("b", b"b%d" % i)
        sub = h.client()
        sub.subscribe("*")
        msgs = drain(sub, 4)
        # global sequence order across topics
        payloads = [(m[0], m[2]) for m in msgs]
        assert payloads == [
            ("a", b"a3"), ("b", b"b3"),
            ("a", b"a4"), ("b", b"b4"),
        ]
    finally:
        h.stop()


# ---------------------------------------------------------------------- #
# subscriber queue overflow policies
# ---------------------------------------------------------------------- #
def test_error_policy_rejects_when_subscriber_queue_full(aof_path):
    # Tiny kernel receive buffer + large frames force backpressure quickly.
    h = BrokerHarness(aof_path, queue_size=4, overflow="error", block_timeout=2)
    try:
        server_sock, client_sock = socket.socketpair()
        for s in (server_sock, client_sock):
            s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024)
        h.server.run_connection(server_sock, peer="slow")
        slow = RawClient(client_sock)
        assert slow.command("SUBSCRIBE", "bulk")[0] == "OK"

        publisher = h.client()
        payload = b"x" * 4096
        got_error = False
        for i in range(500):
            try:
                publisher.publish("bulk", payload)
            except ServerError as exc:
                got_error = True
                assert "queue full" in str(exc)
                break
        assert got_error, "expected queue-full error under 'error' policy"
        stats = publisher.stats()
        assert int(stats["rejected"]) >= 1
        client_sock.close()
        publisher.close()
    finally:
        h.stop()


def test_drop_oldest_keeps_broker_healthy(aof_path):
    h = BrokerHarness(aof_path, queue_size=2, overflow="drop-oldest")
    try:
        server_sock, client_sock = socket.socketpair()
        for s in (server_sock, client_sock):
            s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024)
        h.server.run_connection(server_sock, peer="slow")
        slow = RawClient(client_sock)
        assert slow.command("SUBSCRIBE", "bulk")[0] == "OK"
        publisher = h.client()
        other = h.client()
        seq_numbers = []
        for i in range(100):
            seq_numbers.append(publisher.publish("bulk", b"y" * 4096))
        # Other subscriber and commands keep working; no error returned.
        assert other.ping() is True
        assert max(seq_numbers) == 100
        client_sock.close()
        publisher.close()
        other.close()
    finally:
        h.stop()


def test_block_policy_waits_then_delivers(aof_path):
    # queue large enough that buffer/queue never fills for this volume:
    # blocking policy must behave like ordinary delivery here.
    h = BrokerHarness(aof_path, queue_size=1000, overflow="block", block_timeout=5)
    try:
        sub = h.client()
        pub = h.client()
        sub.subscribe("t")
        for i in range(20):
            pub.publish("t", b"b%d" % i)
        msgs = drain(sub, 20)
        assert [m[2] for m in msgs] == [b"b%d" % i for i in range(20)]
        sub.close()
        pub.close()
    finally:
        h.stop()


def test_block_policy_times_out(aof_path):
    h = BrokerHarness(aof_path, queue_size=2, overflow="block", block_timeout=0.5)
    try:
        server_sock, client_sock = socket.socketpair()
        for s in (server_sock, client_sock):
            s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 512)
        h.server.run_connection(server_sock, peer="slow")
        slow = RawClient(client_sock)
        assert slow.command("SUBSCRIBE", "bulk")[0] == "OK"
        pub = h.client()
        payload = b"z" * 8192
        with pytest.raises(ServerError, match="timed out"):
            # A handful of huge messages must eventually exceed the queue and
            # stay blocked past the 0.5 s timeout.
            for _ in range(50):
                pub.publish("bulk", payload)
        client_sock.close()
        pub.close()
    finally:
        h.stop()
