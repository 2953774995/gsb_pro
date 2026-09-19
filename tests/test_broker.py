import queue

import pytest

from minibroker.broker import (
    Broker,
    InvalidPatternError,
    InvalidTopicError,
    NotSubscribedError,
    QueueFullError,
    pattern_matches,
)


def drain(delivery_queue, count):
    items = []
    for _ in range(count):
        items.append(delivery_queue.get(timeout=1))
    return items


def test_fanout_independent_consumption():
    broker = Broker()
    q1 = broker.register_connection(1)
    q2 = broker.register_connection(2)
    broker.subscribe(1, "t")
    broker.subscribe(2, "t")
    broker.publish("t", b"m1")
    broker.publish("t", b"m2")
    assert [m[2] for m in drain(q1, 2)] == [b"m1", b"m2"]
    assert [m[2] for m in drain(q2, 2)] == [b"m1", b"m2"]


def test_fifo_order_per_subscriber():
    broker = Broker()
    q = broker.register_connection(1)
    broker.subscribe(1, "t")
    for i in range(50):
        broker.publish("t", b"m%d" % i)
    seqs = [m[0] for m in drain(q, 50)]
    assert seqs == sorted(seqs)
    assert seqs == list(range(1, 51))


def test_retained_messages_replayed_to_late_subscriber():
    broker = Broker(retention=100)
    broker.publish("t", b"old1")
    broker.publish("t", b"old2")
    q = broker.register_connection(1)
    broker.subscribe(1, "t")
    assert [m[2] for m in drain(q, 2)] == [b"old1", b"old2"]


def test_retention_limit_keeps_most_recent():
    broker = Broker(retention=3)
    for i in range(10):
        broker.publish("t", b"m%d" % i)
    q = broker.register_connection(1)
    broker.subscribe(1, "t")
    assert [m[2] for m in drain(q, 3)] == [b"m7", b"m8", b"m9"]


def test_retention_zero_drops_unconsumed():
    broker = Broker(retention=0)
    broker.publish("t", b"lost")
    q = broker.register_connection(1)
    broker.subscribe(1, "t")
    with pytest.raises(queue.Empty):
        q.get(timeout=0.1)


def test_retention_zero_still_delivers_to_live_subscribers():
    broker = Broker(retention=0)
    q = broker.register_connection(1)
    broker.subscribe(1, "t")
    broker.publish("t", b"live")
    assert q.get(timeout=1)[2] == b"live"


def test_global_sequence_monotonic_across_topics():
    broker = Broker()
    seqs = [broker.publish("a", b"x"), broker.publish("b", b"x"),
            broker.publish("a", b"x")]
    assert seqs == [1, 2, 3]


def test_unsubscribe_stops_delivery():
    broker = Broker()
    q = broker.register_connection(1)
    broker.subscribe(1, "t")
    broker.unsubscribe(1, "t")
    broker.publish("t", b"nope")
    with pytest.raises(queue.Empty):
        q.get(timeout=0.1)


def test_unsubscribe_without_subscription_raises():
    broker = Broker()
    broker.register_connection(1)
    with pytest.raises(NotSubscribedError):
        broker.unsubscribe(1, "t")


def test_multiple_topics_per_connection():
    broker = Broker()
    q = broker.register_connection(1)
    broker.subscribe(1, "a")
    broker.subscribe(1, "b")
    broker.publish("b", b"2")
    broker.publish("a", b"1")
    broker.publish("c", b"ignored")
    items = drain(q, 2)
    assert [(m[1], m[2]) for m in items] == [("b", b"2"), ("a", b"1")]


def test_queue_full_error_policy():
    broker = Broker(max_queue=2, full_policy="error")
    broker.register_connection(1)
    broker.subscribe(1, "t")
    broker.publish("t", b"1")
    broker.publish("t", b"2")
    with pytest.raises(QueueFullError):
        broker.publish("t", b"3")


def test_queue_full_error_is_atomic():
    broker = Broker(max_queue=1, full_policy="error")
    q1 = broker.register_connection(1)
    q2 = broker.register_connection(2)
    broker.subscribe(1, "t")
    broker.subscribe(2, "t")
    broker.publish("t", b"first")
    q1.get(timeout=1)  # only q1 has room now
    with pytest.raises(QueueFullError):
        broker.publish("t", b"second")
    # Rejected publish must not have reached any subscriber.
    with pytest.raises(queue.Empty):
        q1.get(timeout=0.1)


def test_invalid_topic_rejected():
    broker = Broker()
    for bad in ("", "a b", "a\tb", "a\nb", "a*b"):
        with pytest.raises(InvalidTopicError):
            broker.publish(bad, b"x")


def test_invalid_pattern_rejected():
    broker = Broker()
    broker.register_connection(1)
    for bad in ("", "*", "a b", "a/*b"):
        with pytest.raises(InvalidPatternError):
            broker.subscribe(1, bad)


def test_wildcard_matching():
    assert pattern_matches("foo/*", "foo/bar")
    assert pattern_matches("foo/*", "foo/bar/baz")
    assert not pattern_matches("foo/*", "foo")
    assert not pattern_matches("foo/*", "foobar")
    assert not pattern_matches("foo/*", "other/x")
    assert pattern_matches("foo", "foo")
    assert not pattern_matches("foo", "food")


def test_wildcard_subscription_receives_matching_only():
    broker = Broker()
    q = broker.register_connection(1)
    broker.subscribe(1, "foo/*")
    broker.publish("foo/a", b"1")
    broker.publish("foo/b/c", b"2")
    broker.publish("foo", b"no")
    broker.publish("foobar", b"no")
    items = drain(q, 2)
    assert [m[2] for m in items] == [b"1", b"2"]


def test_wildcard_replay_of_retained_history():
    broker = Broker()
    broker.publish("foo/a", b"1")
    broker.publish("bar/a", b"2")
    broker.publish("foo/b", b"3")
    q = broker.register_connection(1)
    broker.subscribe(1, "foo/*")
    items = drain(q, 2)
    assert [(m[0], m[2]) for m in items] == [(1, b"1"), (3, b"3")]


def test_disconnect_does_not_affect_others():
    broker = Broker()
    q1 = broker.register_connection(1)
    q2 = broker.register_connection(2)
    broker.subscribe(1, "t")
    broker.subscribe(2, "t")
    broker.deregister_connection(1)
    broker.publish("t", b"still-here")
    assert q2.get(timeout=1)[2] == b"still-here"
    assert q1.empty()


def test_flush_clears_retained_but_keeps_sequence():
    broker = Broker()
    broker.publish("t", b"1")
    broker.publish("t", b"2")
    broker.flush()
    assert broker.stats()["stored"] == 0
    assert broker.publish("t", b"3") == 3
    q = broker.register_connection(1)
    broker.subscribe(1, "t")
    items = drain(q, 1)
    assert items[0][2] == b"3"


def test_stats_counts():
    broker = Broker()
    q = broker.register_connection(1)
    broker.subscribe(1, "t")
    broker.publish("t", b"x")
    broker.publish("no-subscribers", b"y")
    stats = broker.stats()
    assert stats["published"] == 2
    assert stats["delivered"] == 1
    assert stats["stored"] == 2
    assert stats["topics"] == 2
    assert stats["connections"] == 1
    assert q.get(timeout=1)[2] == b"x"
