"""Additional edge cases."""

import threading

from minimq import Broker


def test_empty_payload_message(tmp_path):
    b = Broker(str(tmp_path / "d"))
    b.create_topic("t")
    assert b.publish("t", b"") == 0
    c = b.subscribe("t", "g")
    m = c.poll(1)[0]
    assert m.offset == 0 and m.value == b""
    c.ack(0)
    assert c.poll(1) == []
    b.close()


def test_concurrent_polls_single_group_no_duplicates(tmp_path):
    b = Broker(str(tmp_path / "d"))
    b.create_topic("t")
    total = 500
    for i in range(total):
        b.publish("t", str(i))
    consumers = [b.subscribe("t", "g") for _ in range(4)]
    delivered = []
    lock = threading.Lock()

    def worker(c):
        while True:
            msgs = c.poll(10)
            if not msgs:
                return
            for m in msgs:
                with lock:
                    delivered.append(m.offset)

    threads = [threading.Thread(target=worker, args=(c,)) for c in consumers]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(delivered) == list(range(total))
    b.close()


def test_same_group_name_on_different_topics_independent(tmp_path):
    b = Broker(str(tmp_path / "d"))
    b.create_topic("a")
    b.create_topic("b")
    b.publish("a", "a0")
    b.publish("b", "b0")
    ca = b.subscribe("a", "shared")
    cb = b.subscribe("b", "shared")
    assert ca.poll(1)[0].value == b"a0"
    assert cb.poll(1)[0].value == b"b0"
    ca.ack(0)
    hwm_a, _ = b.group_progress("a", "shared")
    hwm_b, _ = b.group_progress("b", "shared")
    assert hwm_a == 1 and hwm_b == 0
    b.close()


def test_offsets_keep_monotonic_across_redelivery(tmp_path):
    b = Broker(str(tmp_path / "d"))
    b.create_topic("t", max_messages=5)
    c1 = b.subscribe("t", "g")
    for i in range(3):
        b.publish("t", str(i))
    c1.poll(3)
    c1.close()
    # replacement consumer redelivers the same offsets
    c2 = b.subscribe("t", "g")
    assert [m.offset for m in c2.poll(3)] == [0, 1, 2]
    c2.ack(0)
    c2.ack(1)
    c2.ack(2)
    c2.close()
    # new messages continue at offset 3
    assert b.publish("t", "new") == 3
    b.close()


def test_context_manager_close(tmp_path):
    with Broker(str(tmp_path / "d")) as b:
        b.create_topic("t")
        b.publish("t", "x")
        with b.subscribe("t", "g") as c:
            assert c.poll(1)[0].value == b"x"
    with Broker(str(tmp_path / "d")) as b2:
        assert b2.topic_info("t")["message_count"] == 1
