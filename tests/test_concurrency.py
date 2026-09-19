"""Concurrency: 10+ clients publishing/subscribing simultaneously."""

import threading
import time

from conftest import recv_all, wait_for

NUM_PUBLISHERS = 6
NUM_SUBSCRIBERS = 6
MESSAGES_PER_PUBLISHER = 50


def test_concurrent_publish_subscribe_no_loss_no_dup(server, client_factory):
    subs = [client_factory() for _ in range(NUM_SUBSCRIBERS)]
    for sub in subs:
        sub.subscribe("t")

    barrier = threading.Barrier(NUM_PUBLISHERS)
    errors = []

    def publisher(idx):
        c = server.connect()
        try:
            barrier.wait(timeout=10)
            for i in range(MESSAGES_PER_PUBLISHER):
                c.publish("t", "p%d-%d" % (idx, i))
        except Exception as exc:  # pragma: no cover - failure path
            errors.append(exc)
        finally:
            c.close()

    threads = [threading.Thread(target=publisher, args=(i,)) for i in range(NUM_PUBLISHERS)]
    for t in threads:
        t.start()

    total = NUM_PUBLISHERS * MESSAGES_PER_PUBLISHER
    expected = {"p%d-%d" % (p, i) for p in range(NUM_PUBLISHERS) for i in range(MESSAGES_PER_PUBLISHER)}

    for sub in subs:
        msgs = recv_all(sub, total, timeout=30)
        payloads = [m.payload.decode() for m in msgs]
        # no loss, no duplication
        assert set(payloads) == expected
        assert len(payloads) == len(set(payloads)) == total
        # global sequence numbers strictly increase in delivery order
        seqs = [m.seq for m in msgs]
        assert seqs == sorted(seqs)
        assert len(set(seqs)) == total

    for t in threads:
        t.join(timeout=30)
    assert not errors
    assert server.broker.last_seq == total


def test_concurrent_publishers_multiple_topics(server):
    topics = ["a", "b", "c"]
    errors = []

    def publisher(idx):
        c = server.connect()
        try:
            for i in range(30):
                c.publish(topics[i % len(topics)], "p%d-%d" % (idx, i))
        except Exception as exc:  # pragma: no cover
            errors.append(exc)
        finally:
            c.close()

    threads = [threading.Thread(target=publisher, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not errors
    assert server.broker.last_seq == 8 * 30
    stats = server.broker.stats()
    assert sum(stats["topics"].values()) == 8 * 30


def test_concurrent_subscribe_unsubscribe_churn(server, client_factory):
    pub = client_factory()
    stop = threading.Event()
    errors = []

    def churn(idx):
        c = server.connect()
        try:
            for i in range(30):
                c.subscribe("t")
                c.unsubscribe("t")
        except Exception as exc:  # pragma: no cover
            errors.append(exc)
        finally:
            c.close()

    threads = [threading.Thread(target=churn, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    while any(t.is_alive() for t in threads):
        pub.publish("t", "x")
        time.sleep(0.005)
    for t in threads:
        t.join(timeout=30)
    assert not errors
    # broker still consistent
    assert server.broker.stats()["subscriptions"] == 0
    assert pub.ping()


def test_slow_subscriber_disconnect_does_not_affect_others(server, client_factory):
    fast = client_factory()
    slow = client_factory()
    fast.subscribe("t")
    slow.subscribe("t")
    pub = client_factory()
    pub.publish("t", "first")
    assert fast.next_message(timeout=2).payload == b"first"
    # slow client disappears abruptly without reading
    slow.close()
    wait_for(lambda: server.broker.stats()["subscriptions"] == 1)
    for i in range(10):
        pub.publish("t", "m%d" % i)
    msgs = recv_all(fast, 10)
    assert [m.payload for m in msgs] == [b"m%d" % i for i in range(10)]
