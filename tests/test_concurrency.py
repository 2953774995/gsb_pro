"""Concurrent publishers / subscribers: no loss, no duplication, order kept."""

import threading

from tests.conftest import wait_until


def test_many_concurrent_publishers_one_subscriber(harness):
    publishers_n = 10
    per_topic = 50
    sub = harness.client()
    sub.subscribe("hot")

    barrier = threading.Barrier(publishers_n)

    def publish_worker():
        client = harness.client()
        barrier.wait()
        for _ in range(per_topic):
            client.publish("hot", b"x")
        client.close()

    threads = [threading.Thread(target=publish_worker) for _ in range(publishers_n)]
    for t in threads:
        t.start()

    total = publishers_n * per_topic
    received = []
    while len(received) < total:
        msg = sub.next_message(5)
        assert msg is not None, "lost messages: got %d/%d" % (len(received), total)
        received.append(msg[1])

    for t in threads:
        t.join(5)
    assert len(received) == total
    assert len(set(received)) == total  # no duplicate global sequences
    assert received == sorted(received)  # FIFO per topic == global order
    sub.close()


def test_many_subscribers_each_get_full_fanout(harness):
    subscribers_n = 12
    messages_n = 30
    subs = [harness.client() for _ in range(subscribers_n)]
    for sub in subs:
        sub.subscribe("fan")

    collected = [[] for _ in range(subscribers_n)]
    start = threading.Event()

    def consume(index):
        start.wait()
        for _ in range(messages_n):
            msg = subs[index].next_message(5)
            assert msg is not None
            collected[index].append(msg[1])

    consumers = [
        threading.Thread(target=consume, args=(i,)) for i in range(subscribers_n)
    ]
    for t in consumers:
        t.start()
    start.set()

    pub = harness.client()
    expected = [pub.publish("fan", b"m") for _ in range(messages_n)]

    for t in consumers:
        t.join(10)
    for index, seqs in enumerate(collected):
        assert seqs == expected, "subscriber %d fan-out mismatch" % index
    for sub in subs:
        sub.close()
    pub.close()


def test_concurrent_publishers_across_topics_global_ordering(harness):
    workers_n = 8
    per_worker = 25

    def worker(worker_id):
        client = harness.client()
        for i in range(per_worker):
            client.publish("w-%d" % worker_id, b"%d" % i)
        client.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(workers_n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)

    monitor = harness.client()
    monitor.subscribe("*")
    seqs = []
    total = workers_n * per_worker
    for _ in range(total):
        msg = monitor.next_message(5)
        assert msg is not None
        seqs.append(msg[1])
    assert sorted(seqs) == list(range(1, total + 1))
    monitor.close()


def test_stats_connections_goes_back_to_zero_after_disconnects(harness):
    clients = [harness.client() for _ in range(10)]
    for client in clients:
        client.ping()
    stats = clients[0].stats()
    assert int(stats["connections"]) >= 10
    for client in clients:
        client.close()
    probe = harness.client()
    assert wait_until(
        lambda: int(probe.stats()["connections"]) == 1, timeout=3
    )
    probe.close()
