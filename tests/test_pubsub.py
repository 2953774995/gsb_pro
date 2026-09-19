"""End-to-end pub/sub semantics over real TCP connections."""

import pytest

from conftest import recv_all


def test_ping(client):
    assert client.ping() is True


def test_publish_after_subscribe_live_delivery(client_factory):
    sub = client_factory()
    pub = client_factory()
    sub.subscribe("t")
    seq = pub.publish("t", "hello")
    msg = sub.next_message(timeout=2)
    assert msg is not None
    assert msg.seq == seq
    assert msg.topic == "t"
    assert msg.payload == b"hello"


def test_publish_before_subscribe_backlog(client_factory):
    pub = client_factory()
    pub.publish("t", "first")
    pub.publish("t", "second")
    sub = client_factory()
    sub.subscribe("t")
    msgs = recv_all(sub, 2)
    assert [m.payload for m in msgs] == [b"first", b"second"]
    assert [m.seq for m in msgs] == [1, 2]


def test_retention_zero_discards(server_factory):
    srv = server_factory(retention=0)
    pub = srv.connect()
    pub.publish("t", "lost")
    sub = srv.connect()
    sub.subscribe("t")
    assert sub.next_message(timeout=0.4) is None
    pub.publish("t", "live")
    msg = sub.next_message(timeout=2)
    assert msg.payload == b"live"
    pub.close()
    sub.close()


def test_fanout_multiple_subscribers(client_factory):
    sub1 = client_factory()
    sub2 = client_factory()
    sub3 = client_factory()  # subscribed to a different topic
    pub = client_factory()
    sub1.subscribe("t")
    sub2.subscribe("t")
    sub3.subscribe("other")
    for i in range(5):
        pub.publish("t", "m%d" % i)
    for sub in (sub1, sub2):
        msgs = recv_all(sub, 5)
        assert [m.payload for m in msgs] == [b"m%d" % i for i in range(5)]
        assert [m.seq for m in msgs] == [1, 2, 3, 4, 5]
    assert sub3.next_message(timeout=0.3) is None


def test_unsubscribe(client_factory):
    sub = client_factory()
    pub = client_factory()
    sub.subscribe("t")
    pub.publish("t", "a")
    assert sub.next_message(timeout=2).payload == b"a"
    sub.unsubscribe("t")
    pub.publish("t", "b")
    assert sub.next_message(timeout=0.3) is None


def test_wildcard_subscription_over_tcp(client_factory):
    sub = client_factory()
    pub = client_factory()
    sub.subscribe("news/*")
    pub.publish("news/tech", "a")
    pub.publish("other", "b")
    pub.publish("news/sports", "c")
    msgs = recv_all(sub, 2)
    assert [m.topic for m in msgs] == ["news/tech", "news/sports"]


def test_global_seq_monotonic_across_topics(client_factory):
    sub = client_factory()
    pub = client_factory()
    sub.subscribe("a")
    sub.subscribe("b")
    seqs = [pub.publish(t, "x") for t in ("a", "b", "a", "b", "a")]
    assert seqs == sorted(seqs) and len(set(seqs)) == 5
    msgs = recv_all(sub, 5)
    assert [m.seq for m in msgs] == seqs


def test_binary_payload_roundtrip(client_factory):
    sub = client_factory()
    pub = client_factory()
    sub.subscribe("bin")
    payload = bytes(range(256)) + b"\n\r\t spaces \x00"
    pub.publish("bin", payload)
    msg = sub.next_message(timeout=2)
    assert msg.payload == payload


def test_empty_payload(client_factory):
    sub = client_factory()
    pub = client_factory()
    sub.subscribe("t")
    pub.publish("t", b"")
    msg = sub.next_message(timeout=2)
    assert msg.payload == b""


def test_multiple_topics_same_connection(client_factory):
    sub = client_factory()
    pub = client_factory()
    sub.subscribe("a")
    sub.subscribe("b")
    pub.publish("a", "1")
    pub.publish("b", "2")
    msgs = recv_all(sub, 2)
    assert {(m.topic, m.payload) for m in msgs} == {("a", b"1"), ("b", b"2")}


def test_stats_command(client_factory):
    sub = client_factory()
    pub = client_factory()
    sub.subscribe("t")
    pub.publish("t", "x")
    stats = pub.stats()
    assert stats["last_seq"] == 1
    assert stats["published_total"] == 1
    assert stats["subscriptions"] == 1
    assert stats["topics"] == {"t": 1}
    assert stats["connections"] >= 2


def test_flush_clears_retained(client_factory):
    pub = client_factory()
    pub.publish("t", "x")
    pub.flush()
    stats = pub.stats()
    assert stats["topics"] == {}
    sub = client_factory()
    sub.subscribe("t")
    assert sub.next_message(timeout=0.3) is None
    # sequence numbers keep increasing after a flush
    assert pub.publish("t", "y") == 2
