"""End-to-end publish/subscribe semantics."""

import pytest

from minibroker.errors import ServerError
from tests.conftest import drain, wait_until


def test_ping(harness):
    client = harness.client()
    assert client.ping() is True


def test_publish_after_subscribe_delivered(harness):
    sub = harness.client()
    pub = harness.client()
    sub.subscribe("news")
    assert pub.publish("news", b"hello") == 1
    topic, seq, payload = sub.next_message(2)
    assert (topic, seq, payload) == ("news", 1, b"hello")


def test_payload_preserves_spaces_tabs_newlines_and_nulls(harness):
    sub = harness.client()
    pub = harness.client()
    sub.subscribe("bin")
    blob = b"space here\ttab\nnewline\r\n\x00\xff\xfe"
    seq = pub.publish("bin", blob)
    _, got_seq, got = sub.next_message(2)
    assert got_seq == seq and got == blob


def test_messages_are_fifo_per_topic(harness):
    sub = harness.client()
    pub = harness.client()
    sub.subscribe("q")
    for i in range(20):
        pub.publish("q", b"m%02d" % i)
    msgs = drain(sub, 20)
    assert [m[1] for m in msgs] == list(range(1, 21))
    assert [m[2] for m in msgs] == [b"m%02d" % i for i in range(20)]


def test_multiple_subscribers_fan_out(harness):
    subs = [harness.client() for _ in range(3)]
    pub = harness.client()
    for sub in subs:
        sub.subscribe("channel")
    for i in range(5):
        pub.publish("channel", b"x%d" % i)
    for sub in subs:
        msgs = drain(sub, 5)
        assert [(m[1], m[2]) for m in msgs] == [
            (i + 1, b"x%d" % i) for i in range(5)
        ]


def test_different_topics_are_isolated(harness):
    a = harness.client()
    b = harness.client()
    pub = harness.client()
    a.subscribe("a")
    b.subscribe("b")
    pub.publish("a", b"for-a")
    pub.publish("b", b"for-b")
    assert a.next_message(2)[2] == b"for-a"
    assert b.next_message(2)[2] == b"for-b"
    assert a.next_message(timeout=0.2) is None
    assert b.next_message(timeout=0.2) is None


def test_subscribe_to_multiple_topics_on_one_connection(harness):
    sub = harness.client()
    pub = harness.client()
    sub.subscribe("t1")
    sub.subscribe("t2")
    pub.publish("t1", b"1")
    pub.publish("t2", b"2")
    pub.publish("t1", b"3")
    msgs = drain(sub, 3)
    assert [(m[0], m[2]) for m in msgs] == [
        ("t1", b"1"),
        ("t2", b"2"),
        ("t1", b"3"),
    ]


def test_unsubscribe_stops_delivery(harness):
    sub = harness.client()
    pub = harness.client()
    sub.subscribe("t")
    pub.publish("t", b"before")
    assert sub.next_message(2)[2] == b"before"
    sub.unsubscribe("t")
    pub.publish("t", b"after")
    assert sub.next_message(timeout=0.2) is None


def test_unsubscribe_unknown_returns_error(harness):
    client = harness.client()
    with pytest.raises(ServerError, match="not subscribed"):
        client.unsubscribe("nope")


def test_resubscribe_does_not_duplicate(harness):
    sub = harness.client()
    pub = harness.client()
    sub.subscribe("t")
    sub.subscribe("t")  # idempotent
    pub.publish("t", b"only once")
    assert sub.next_message(2)[2] == b"only once"
    assert sub.next_message(timeout=0.2) is None


# ---------------------------------------------------------------------- #
# global sequence numbers
# ---------------------------------------------------------------------- #
def test_global_sequence_monotonic_across_topics(harness):
    pub = harness.client()
    seqs = []
    for i in range(10):
        seqs.append(pub.publish("topic-%d" % (i % 3), b"p"))
    assert seqs == list(range(1, 11))


def test_sequence_reported_on_messages_matches_publish(harness):
    sub = harness.client()
    pub = harness.client()
    sub.subscribe("s")
    got = []
    for i in range(5):
        got.append(pub.publish("s", b"%d" % i))
    delivered = drain(sub, 5)
    assert [m[1] for m in delivered] == got


# ---------------------------------------------------------------------- #
# wildcards
# ---------------------------------------------------------------------- #
def test_wildcard_subscribe_prefix(harness):
    sub = harness.client()
    pub = harness.client()
    sub.subscribe("news/*")
    for topic in ["news", "news/sports", "news/sports/local"]:
        pub.publish(topic, b"@" + topic.encode())
    pub.publish("newsletter", b"must-not-arrive")
    msgs = drain(sub, 3)
    assert [m[0] for m in msgs] == ["news", "news/sports", "news/sports/local"]
    assert sub.next_message(timeout=0.2) is None


def test_global_wildcard_receives_everything(harness):
    sub = harness.client()
    pub = harness.client()
    sub.subscribe("*")
    pub.publish("a", b"1")
    pub.publish("b/c", b"2")
    msgs = drain(sub, 2)
    assert [m[0] for m in msgs] == ["a", "b/c"]


def test_overlapping_subscriptions_deliver_once(harness):
    sub = harness.client()
    pub = harness.client()
    sub.subscribe("*")
    sub.subscribe("t/*")
    sub.subscribe("t/x")
    pub.publish("t/x", b"x")
    msg = sub.next_message(2)
    assert msg is not None and msg[2] == b"x"
    assert sub.next_message(timeout=0.2) is None


def test_exact_and_wildcard_subscribers_both_get_message(harness):
    exact = harness.client()
    wild = harness.client()
    pub = harness.client()
    exact.subscribe("t/x")
    wild.subscribe("t/*")
    pub.publish("t/x", b"both")
    assert exact.next_message(2)[2] == b"both"
    assert wild.next_message(2)[2] == b"both"


# ---------------------------------------------------------------------- #
# stats
# ---------------------------------------------------------------------- #
def test_stats_reflects_state(harness):
    pub = harness.client()
    sub = harness.client()
    sub.subscribe("t")
    for i in range(3):
        pub.publish("t", b"x")
    drain(sub, 3)
    stats = pub.stats()
    assert int(stats["seq"]) == 3
    assert int(stats["published"]) == 3
    assert int(stats["subscriptions"]) == 1
    assert int(stats["connections"]) >= 2
