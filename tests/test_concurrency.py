"""Concurrency: many producers and consumers hammering one broker."""

import threading
import time

from minimq import Broker

PRODUCERS = 4
MESSAGES_PER_PRODUCER = 50
CONSUMERS = 3
TOTAL = PRODUCERS * MESSAGES_PER_PRODUCER


def test_concurrent_producers_and_consumers(tmp_path):
    broker = Broker(data_dir=str(tmp_path / "mq"), fsync=False)
    broker.create_topic("t")

    def produce(pid):
        for i in range(MESSAGES_PER_PRODUCER):
            broker.publish("t", "p%d-m%d" % (pid, i))

    consumed = []
    consumed_lock = threading.Lock()
    done = threading.Event()

    def consume():
        consumer = broker.subscribe("t", "g")
        while not done.is_set():
            messages = consumer.poll(10)
            if not messages:
                time.sleep(0.001)
                continue
            with consumed_lock:
                for m in messages:
                    consumed.append(m.offset)
                    consumer.ack(m.offset)

    producers = [threading.Thread(target=produce, args=(p,))
                 for p in range(PRODUCERS)]
    consumers = [threading.Thread(target=consume) for _ in range(CONSUMERS)]
    for t in consumers:
        t.start()
    for t in producers:
        t.start()
    for t in producers:
        t.join()

    deadline = time.time() + 30
    while True:
        with consumed_lock:
            count = len(consumed)
        if count >= TOTAL:
            break
        assert time.time() < deadline, "consumers stalled at %d/%d" % (
            count, TOTAL)
        time.sleep(0.01)
    done.set()
    for t in consumers:
        t.join()

    # Exactly-once within the group: every offset consumed exactly once.
    assert sorted(consumed) == list(range(TOTAL))

    # Offsets are unique and dense: no two producers got the same offset.
    info = broker.list_topics()[0]
    assert info["next_offset"] == TOTAL
    broker.close()


def test_concurrent_publishers_on_multiple_topics(tmp_path):
    broker = Broker(data_dir=str(tmp_path / "mq"), fsync=False)
    topics = ["a", "b", "c"]
    for name in topics:
        broker.create_topic(name)

    def produce(topic):
        for i in range(30):
            broker.publish(topic, "m%d" % i)

    threads = [threading.Thread(target=produce, args=(t,)) for t in topics]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    infos = {i["name"]: i for i in broker.list_topics()}
    for name in topics:
        assert infos[name]["next_offset"] == 30
    broker.close()
