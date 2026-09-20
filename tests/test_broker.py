import pytest

from minibroker.exceptions import BrokerError, QueueFullError


def test_publish_returns_global_monotonic_sequences(make_broker, fake_connection_factory):
    broker, _ = make_broker(retention=10)
    a = fake_connection_factory(broker)
    b = fake_connection_factory(broker)
    broker.subscribe(a, b"a")
    broker.subscribe(b, b"b")
    sequences = [
        broker.publish(b"a", b"1").sequence,
        broker.publish(b"b", b"2").sequence,
        broker.publish(b"a", b"3").sequence,
        broker.publish(b"other", b"4").sequence,
    ]
    assert sequences == [1, 2, 3, 4]
    assert [m.sequence for m in a.pop_all()] == [1, 3]
    assert [m.sequence for m in b.pop_all()] == [2]


def test_retained_messages_backfill_subscribers(make_broker, fake_connection_factory):
    broker, _ = make_broker(retention=1000)
    broker.publish(b"t", b"before-1")
    broker.publish(b"t", b"before-2")
    subscriber = fake_connection_factory(broker)
    broker.subscribe(subscriber, b"t")
    broker.publish(b"t", b"after")
    messages = subscriber.pop_all()
    assert [(m.sequence, m.payload) for m in messages] == [
        (1, b"before-1"),
        (2, b"before-2"),
        (3, b"after"),
    ]


def test_retention_zero_discards_without_subscribers(make_broker, fake_connection_factory):
    broker, _ = make_broker(retention=0)
    broker.publish(b"t", b"lost")
    subscriber = fake_connection_factory(broker)
    broker.subscribe(subscriber, b"t")
    broker.publish(b"t", b"kept")
    assert [m.payload for m in subscriber.pop_all()] == [b"kept"]


def test_retention_keeps_only_last_n(make_broker, fake_connection_factory):
    broker, _ = make_broker(retention=2)
    for idx in range(5):
        broker.publish(b"t", str(idx).encode())
    subscriber = fake_connection_factory(broker)
    broker.subscribe(subscriber, b"t")
    assert [m.payload for m in subscriber.pop_all()] == [b"3", b"4"]


def test_fanout_is_independent_and_no_duplicates(make_broker, fake_connection_factory):
    broker, _ = make_broker(retention=10)
    one = fake_connection_factory(broker)
    two = fake_connection_factory(broker)
    broker.subscribe(one, b"shared")
    broker.subscribe(two, b"shared")
    broker.publish(b"shared", b"m1")
    broker.publish(b"shared", b"m2")
    assert [m.payload for m in one.pop_all()] == [b"m1", b"m2"]
    assert [m.payload for m in two.pop_all()] == [b"m1", b"m2"]


def test_unsubscribe_and_disconnect_do_not_affect_others(make_broker, fake_connection_factory):
    broker, _ = make_broker(retention=10)
    leaving = fake_connection_factory(broker)
    staying = fake_connection_factory(broker)
    broker.subscribe(leaving, b"t")
    broker.subscribe(staying, b"t")
    broker.publish(b"t", b"first")
    assert broker.unsubscribe(leaving, b"t") is True
    broker.publish(b"t", b"second")
    broker.unregister_connection(leaving)
    broker.publish(b"t", b"third")
    assert [m.payload for m in staying.pop_all()] == [b"first", b"second", b"third"]
    # Disconnect cleanup drops that socket's undelivered local queue without
    # affecting retained routing state or any other subscriber.
    assert leaving.pending_count() == 0


def test_unsubscribe_removes_undelivered_queued_message(make_broker, fake_connection_factory):
    broker, _ = make_broker(retention=10)
    conn = fake_connection_factory(broker)
    broker.subscribe(conn, b"t")
    broker.publish(b"t", b"pending")
    broker.unsubscribe(conn, b"t")
    assert conn.pending_count() == 0


def test_wildcard_prefix_subscription(make_broker, fake_connection_factory):
    broker, _ = make_broker(retention=10)
    broker.publish(b"news/sports/a", b"old-sports")
    broker.publish(b"news/tech", b"old-tech")
    broker.publish(b"other", b"old-other")
    sports = fake_connection_factory(broker)
    all_news = fake_connection_factory(broker)
    everything = fake_connection_factory(broker)
    broker.subscribe(sports, b"news/sports/*")
    broker.subscribe(all_news, b"news/*")
    broker.subscribe(everything, b"*")
    broker.publish(b"news/sports/game", b"new-game")
    broker.publish(b"news/tech", b"new-tech")
    broker.publish(b"misc", b"new-misc")

    assert [m.payload for m in sports.pop_all()] == [b"old-sports", b"new-game"]
    assert [m.payload for m in all_news.pop_all()] == [
        b"old-sports", b"old-tech", b"new-game", b"new-tech"
    ]
    assert [m.payload for m in everything.pop_all()] == [
        b"old-sports", b"old-tech", b"old-other",
        b"new-game", b"new-tech", b"new-misc",
    ]


def test_wildcard_requires_path_segment(make_broker, fake_connection_factory):
    broker, _ = make_broker(retention=10)
    conn = fake_connection_factory(broker)
    broker.subscribe(conn, b"news/*")
    broker.publish(b"news", b"root")
    broker.publish(b"news/tech/x", b"child")
    assert [m.payload for m in conn.pop_all()] == [b"child"]


def test_overlapping_wildcards_deliver_once_per_connection(make_broker, fake_connection_factory):
    broker, _ = make_broker(retention=10)
    conn = fake_connection_factory(broker)
    broker.subscribe(conn, b"*")
    broker.subscribe(conn, b"a/*")
    broker.subscribe(conn, b"a/b/*")
    broker.publish(b"a/b/c", b"x")
    assert [m.payload for m in conn.pop_all()] == [b"x"]


@pytest.mark.parametrize("topic", [b"", b"bad\ntopic", b"bad\ttopic", b"bad\x00", b"bad*topic", b"bad/*x"])
def test_invalid_topics_return_broker_errors(make_broker, fake_connection_factory, topic):
    broker, _ = make_broker(retention=10)
    conn = fake_connection_factory(broker)
    with pytest.raises(BrokerError):
        broker.publish(topic, b"x")
    with pytest.raises(BrokerError):
        broker.subscribe(conn, topic)


def test_client_queue_limit_rejects_without_partial_fanout(make_broker, fake_connection_factory):
    broker, _ = make_broker(retention=10, max_client_queue=1)
    full = fake_connection_factory(broker)
    empty = fake_connection_factory(broker)
    broker.subscribe(full, b"t")
    broker.subscribe(empty, b"t")
    broker.publish(b"t", b"fill")
    with pytest.raises(QueueFullError):
        broker.publish(b"t", b"reject")
    assert [m.payload for m in full.pop_all()] == [b"fill"]
    assert [m.payload for m in empty.pop_all()] == [b"fill"]
    broker.publish(b"t", b"after")
    assert [m.payload for m in full.pop_all()] == [b"after"]
    assert [m.payload for m in empty.pop_all()] == [b"after"]


def test_flush_clears_retention_and_pending_and_resets_sequence(make_broker, fake_connection_factory):
    broker, _ = make_broker(retention=10)
    conn = fake_connection_factory(broker)
    broker.subscribe(conn, b"t")
    broker.publish(b"t", b"old")
    broker.flush()
    new = fake_connection_factory(broker)
    broker.subscribe(new, b"t")
    message = broker.publish(b"t", b"new")
    assert message.sequence == 1
    assert conn.pop_all() == [message]
    assert new.pop_all() == [message]


def test_overlapping_subscriptions_never_duplicate_history(make_broker, fake_connection_factory):
    broker, _ = make_broker(retention=10)
    conn = fake_connection_factory(broker)
    broker.subscribe(conn, b"a/*")
    broker.publish(b"a/b/c", b"first")
    assert [m.payload for m in conn.pop_all()] == [b"first"]

    # A narrower later subscription matches retained history already delivered
    # through the broader subscription, so it must not replay it.
    broker.subscribe(conn, b"a/b/*")
    broker.publish(b"a/b/c", b"second")
    assert [m.payload for m in conn.pop_all()] == [b"second"]


def test_wildcard_does_not_match_empty_hierarchical_segments(make_broker, fake_connection_factory):
    from minibroker.topics import topic_matches_prefix

    assert topic_matches_prefix(b"a/b", b"a")
    assert not topic_matches_prefix(b"a//b", b"a")
    assert not topic_matches_prefix(b"a/", b"a")
    broker, _ = make_broker(retention=10)
    conn = fake_connection_factory(broker)
    broker.subscribe(conn, b"a/*")
    broker.publish(b"a//b", b"empty-segment")
    broker.publish(b"a/b", b"valid")
    assert [m.payload for m in conn.pop_all()] == [b"valid"]
