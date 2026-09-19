"""Concurrent producers and consumers: no lost or duplicated messages."""

import threading

from minimq import Broker

N_PRODUCERS = 4
PER_PRODUCER = 200
N_CONSUMERS = 3


def test_concurrent_producers_monotonic_offsets(tmp_path):
    b = Broker(str(tmp_path / "d"))
    b.create_topic("t")
    all_offsets = []
    lock = threading.Lock()

    def produce(pid):
        local = []
        for i in range(PER_PRODUCER):
            local.append(b.publish("t", "p{}-{}".format(pid, i)))
        with lock:
            all_offsets.extend(local)

    threads = [threading.Thread(target=produce, args=(p,)) for p in range(N_PRODUCERS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    expected = N_PRODUCERS * PER_PRODUCER
    assert sorted(all_offsets) == list(range(expected))
    assert len(set(all_offsets)) == expected
    b.close()


def test_concurrent_consumers_no_duplicates(tmp_path):
    b = Broker(str(tmp_path / "d"))
    b.create_topic("t")
    total = N_PRODUCERS * PER_PRODUCER
    for i in range(total):
        b.publish("t", str(i))

    received = []
    received_lock = threading.Lock()
    stop = threading.Event()

    def consume():
        c = b.subscribe("t", "grp")
        while not stop.is_set():
            msgs = c.poll(50)
            if not msgs:
                if stop.is_set():
                    break
                # a tiny sleep just reduces spinning
                stop.wait(0.001)
                continue
            for m in msgs:
                c.ack(m.offset)
                with received_lock:
                    received.append(m.offset)
        c.close()

    consumers = [threading.Thread(target=consume) for _ in range(N_CONSUMERS)]
    for t in consumers:
        t.start()

    # Wait for consumption of every message, then signal stop.
    while True:
        with received_lock:
            if len(received) >= total:
                break
        stop.wait(0.01)
    stop.set()
    for t in consumers:
        t.join(timeout=5)

    assert len(received) == total
    assert sorted(received) == list(range(total))

    # After restart, nothing is redelivered to the group.
    b.close()
    b2 = Broker(str(tmp_path / "d"))
    c = b2.subscribe("t", "grp")
    assert c.poll(100) == []
    b2.close()


def test_concurrent_produce_and_consume(tmp_path):
    b = Broker(str(tmp_path / "d"))
    b.create_topic("t")
    got = []
    got_lock = threading.Lock()
    total = 300
    stop = threading.Event()

    def producer():
        for i in range(total):
            b.publish("t", str(i))

    def consumer():
        c = b.subscribe("t", "grp")
        while not stop.is_set():
            for m in c.poll(20):
                c.ack(m.offset)
                with got_lock:
                    got.append(m.offset)
        c.close()

    p = threading.Thread(target=producer)
    cs = [threading.Thread(target=consumer) for _ in range(2)]
    p.start()
    for t in cs:
        t.start()
    p.join()
    while len(got) < total:
        stop.wait(0.01)
    stop.set()
    for t in cs:
        t.join(timeout=5)
    assert sorted(got) == list(range(total))
    b.close()
