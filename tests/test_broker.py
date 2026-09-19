"""Unit tests for the broker core (no networking involved)."""

import threading
import time

import pytest

from minibroker.broker import Broker, Mailbox, QueueFull


def drain(mailbox, count, timeout=2.0):
    items = []
    deadline = time.time() + timeout
    while len(items) < count:
        remaining = deadline - time.time()
        assert remaining > 0, "timed out draining mailbox"
        items.append(mailbox.queue.get(timeout=remaining))
    return items


def test_publish_returns_increasing_seq():
    b = Broker()
    assert b.publish("t", b"a") == 1
    assert b.publish("t", b"b") == 2
    assert b.publish("other", b"c") == 3


def test_fanout_and_fifo_order():
    b = Broker()
    m1, m2 = Mailbox(), Mailbox()
    b.subscribe(1, "t", m1)
    b.subscribe(2, "t", m2)
    for i in range(5):
        b.publish("t", b"msg-%d" % i)
    for mb in (m1, m2):
        items = drain(mb, 5)
        assert [it[0] for it in items] == [1, 2, 3, 4, 5]
        assert [it[2] for it in items] == [b"msg-%d" % i for i in range(5)]


def test_backlog_replayed_on_subscribe():
    b = Broker()
    b.publish("t", b"old-1")
    b.publish("t", b"old-2")
    mb = Mailbox()
    b.subscribe(1, "t", mb)
    assert [it[2] for it in drain(mb, 2)] == [b"old-1", b"old-2"]
    # live messages continue after the backlog
    b.publish("t", b"live")
    assert drain(mb, 1)[0][2] == b"live"


def test_retention_zero_discards_without_subscriber():
    b = Broker(retention=0)
    b.publish("t", b"lost")
    mb = Mailbox()
    b.subscribe(1, "t", mb)
    assert mb.queue.empty()
    # live delivery still works
    b.publish("t", b"live")
    assert drain(mb, 1)[0][2] == b"live"


def test_retention_keeps_only_last_n():
    b = Broker(retention=3)
    for i in range(10):
        b.publish("t", b"m%d" % i)
    mb = Mailbox()
    b.subscribe(1, "t", mb)
    assert [it[2] for it in drain(mb, 3)] == [b"m7", b"m8", b"m9"]


def test_wildcard_subscription():
    b = Broker()
    mb = Mailbox()
    b.subscribe(1, "news/*", mb)
    b.publish("news/tech", b"a")
    b.publish("news/sports", b"b")
    b.publish("other", b"c")
    items = drain(mb, 2)
    assert [it[1] for it in items] == ["news/tech", "news/sports"]
    assert mb.queue.empty()


def test_wildcard_backlog_replay():
    b = Broker()
    b.publish("news/a", b"1")
    b.publish("other/b", b"2")
    b.publish("news/c", b"3")
    mb = Mailbox()
    b.subscribe(1, "news/*", mb)
    items = drain(mb, 2)
    assert [it[0] for it in items] == [1, 3]  # seq order preserved


def test_duplicate_matching_patterns_deliver_once():
    b = Broker()
    mb = Mailbox()
    b.subscribe(1, "news/*", mb)
    b.subscribe(1, "news/a", mb)
    b.publish("news/a", b"x")
    drain(mb, 1)
    assert mb.queue.empty()


def test_unsubscribe_stops_delivery():
    b = Broker()
    mb = Mailbox()
    b.subscribe(1, "t", mb)
    b.publish("t", b"before")
    assert b.unsubscribe(1, "t") is True
    b.publish("t", b"after")
    assert [it[2] for it in drain(mb, 1)] == [b"before"]
    assert mb.queue.empty()
    assert b.unsubscribe(1, "t") is False


def test_connection_closed_removes_subscriptions():
    b = Broker()
    mb = Mailbox()
    b.subscribe(1, "t", mb)
    b.connection_closed(1)
    b.publish("t", b"x")
    assert mb.queue.empty()
    assert b.stats()["subscriptions"] == 0


def test_invalid_topic_rejected():
    b = Broker()
    with pytest.raises(ValueError):
        b.publish("", b"x")
    with pytest.raises(ValueError):
        b.publish("bad topic", b"x")
    with pytest.raises(ValueError):
        b.publish("bad\x01topic", b"x")


def test_on_full_error_policy():
    b = Broker(on_full="error")
    mb = Mailbox(maxsize=2)
    b.subscribe(1, "t", mb)
    b.publish("t", b"1")
    b.publish("t", b"2")
    with pytest.raises(QueueFull):
        b.publish("t", b"3")
    # failed publish must not be stored anywhere
    assert b.last_seq == 2
    mb2 = Mailbox()
    b.subscribe(2, "t", mb2)
    assert [it[2] for it in drain(mb2, 2)] == [b"1", b"2"]


def test_on_full_block_policy():
    b = Broker(on_full="block")
    mb = Mailbox(maxsize=1)
    b.subscribe(1, "t", mb)
    b.publish("t", b"1")  # fills the mailbox

    done = threading.Event()

    def publisher():
        b.publish("t", b"2")
        done.set()

    t = threading.Thread(target=publisher)
    t.start()
    time.sleep(0.2)
    assert not done.is_set()  # publisher is blocked
    mb.queue.get(timeout=1)  # free one slot
    t.join(timeout=2)
    assert done.is_set()
    assert drain(mb, 1)[0][2] == b"2"


def test_block_policy_unblocks_when_subscriber_disconnects():
    b = Broker(on_full="block")
    alive = {"v": True}
    mb = Mailbox(maxsize=1, is_alive=lambda: alive["v"])
    b.subscribe(1, "t", mb)
    b.publish("t", b"1")
    alive["v"] = False
    with pytest.raises(QueueFull):
        b.publish("t", b"2")


def test_flush_clears_backlog_keeps_seq():
    b = Broker()
    b.publish("t", b"1")
    b.flush()
    mb = Mailbox()
    b.subscribe(1, "t", mb)
    assert mb.queue.empty()
    assert b.publish("t", b"2") == 2  # seq keeps increasing


def test_stats():
    b = Broker()
    b.publish("a", b"1")
    b.publish("a", b"2")
    b.publish("b", b"3")
    mb = Mailbox()
    b.subscribe(1, "a", mb)
    stats = b.stats()
    assert stats["last_seq"] == 3
    assert stats["published_total"] == 3
    assert stats["topics"] == {"a": 2, "b": 1}
    assert stats["subscriptions"] == 1
