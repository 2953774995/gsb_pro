import threading
import time

import pytest

from linebus.broker import Broker, BrokerError, BrokerShutdown
from linebus.persistence import AOFCorrupt, AOFTruncated, read_aof
from linebus.storage import Event


def drain(client_id, broker, count, timeout=3):
    return [broker.next_event(client_id, timeout=timeout) for _ in range(count)]


def test_basic_replay_before_subscribe_then_live_after(tmp_path):
    broker = Broker(retention=1000, aof_path=str(tmp_path / "aof"), fsync=True)
    try:
        first = broker.publish("q", b"before")
        sub = broker.add_subscriber()
        broker.subscribe(sub, "q")
        assert broker.next_event(sub, timeout=1) == Event(first.sequence, "q", b"before")
        second = broker.publish("q", b"after")
        assert broker.next_event(sub, timeout=1) == Event(second.sequence, "q", b"after")
    finally:
        broker.close()


def test_no_subscriber_retention_keeps_latest_n_and_zero_discards(tmp_path):
    retained = Broker(retention=2, aof_path=str(tmp_path / "a1"), fsync=True)
    try:
        for value in range(4):
            retained.publish("q", str(value).encode())
        sub = retained.add_subscriber()
        retained.subscribe(sub, "q")
        assert [msg.payload for msg in drain(sub, retained, 2)] == [b"2", b"3"]
    finally:
        retained.close()

    discard = Broker(retention=0, aof_path=str(tmp_path / "a2"), fsync=True)
    try:
        discard.publish("q", b"gone")
        sub = discard.add_subscriber()
        discard.subscribe(sub, "q")
        assert discard.next_event(sub, timeout=0.05) is None
    finally:
        discard.close()


def test_fanout_is_independent_and_global_sequence_monotonic(tmp_path):
    broker = Broker(retention=0, aof_path=str(tmp_path / "aof"), fsync=True)
    try:
        s1 = broker.add_subscriber()
        s2 = broker.add_subscriber()
        broker.subscribe(s1, "q")
        broker.subscribe(s2, "q")
        sequences = []
        for i in range(20):
            sequences.append(broker.publish("q", str(i).encode()).sequence)
        assert sequences == list(range(1, 21))
        assert [msg.payload for msg in drain(s1, broker, 20)] == [str(i).encode() for i in range(20)]
        assert [msg.payload for msg in drain(s2, broker, 20)] == [str(i).encode() for i in range(20)]
    finally:
        broker.close()


def test_multiple_and_wildcard_subscriptions_do_not_duplicate(tmp_path):
    broker = Broker(retention=10, aof_path=str(tmp_path / "aof"), fsync=True)
    try:
        sub = broker.add_subscriber()
        broker.subscribe(sub, "quality")
        broker.subscribe(sub, "quality/*")
        broker.publish("quality", b"x")
        broker.publish("quality/c1", b"y")
        broker.publish("quality/c2/depth", b"z")
        messages = [broker.next_event(sub, timeout=1) for _ in range(3)]
        assert [(m.sequence, m.payload) for m in messages] == [
            (1, b"x"),
            (2, b"y"),
            (3, b"z"),
        ]
    finally:
        broker.close()


def test_queue_full_error_policy(tmp_path):
    broker = Broker(
        retention=0,
        queue_capacity=1,
        queue_full_policy="error",
        aof_path=str(tmp_path / "aof"),
        fsync=True,
    )
    try:
        sub = broker.add_subscriber()
        broker.subscribe(sub, "q")
        broker.publish("q", b"1")
        with pytest.raises(BrokerError, match="full"):
            broker.publish("q", b"2")
        assert broker.next_event(sub, timeout=1).payload == b"1"
    finally:
        broker.close()


def test_block_policy_backpressure_eventually_delivers(tmp_path):
    broker = Broker(
        retention=0,
        queue_capacity=1,
        queue_full_policy="block",
        aof_path=str(tmp_path / "aof"),
        fsync=True,
    )
    try:
        sub = broker.add_subscriber()
        broker.subscribe(sub, "q")
        result = []
        broker.publish("q", b"first")

        def publish():
            result.append(broker.publish("q", b"blocked"))

        thread = threading.Thread(target=publish)
        thread.start()
        time.sleep(0.1)
        assert thread.is_alive()
        assert broker.next_event(sub, timeout=2).payload == b"first"
        assert broker.next_event(sub, timeout=2).payload == b"blocked"
        thread.join(timeout=2)
        assert not thread.is_alive()
    finally:
        broker.close()


def test_flush_clears_memory_and_aof(tmp_path):
    path = str(tmp_path / "aof")
    broker = Broker(retention=10, aof_path=path, fsync=True)
    try:
        broker.publish("q", b"x")
        broker.flush()
        sub = broker.add_subscriber()
        broker.subscribe(sub, "q")
        assert broker.next_event(sub, timeout=0.05) is None
    finally:
        broker.close()
    events, next_sequence = read_aof(path)
    assert events == []
    assert next_sequence == 1


def test_aof_recovery_and_sequence_continuity(tmp_path):
    path = str(tmp_path / "aof")
    first = Broker(aof_path=path, fsync=True)
    try:
        first.publish("q", b"a")
        first.publish("other", b"b")
    finally:
        first.close()

    second = Broker(aof_path=path, fsync=True)
    try:
        event = second.publish("q", b"c")
        assert event.sequence == 3
        sub = second.add_subscriber()
        second.subscribe(sub, "q")
        messages = drain(sub, second, 2)
        assert [(m.sequence, m.payload) for m in messages] == [(1, b"a"), (3, b"c")]
    finally:
        second.close()


def test_corrupt_and_truncated_aof_are_detected(tmp_path):
    path = tmp_path / "aof"
    path.write_bytes(b"P 1 1 5\nhi")
    with pytest.raises(AOFTruncated):
        read_aof(str(path))
    path.write_bytes(b"P 2 1 0\nq")
    with pytest.raises(AOFCorrupt):
        read_aof(str(path))


def test_shutdown_unblocks_consumers_and_publishers(tmp_path):
    broker = Broker(aof_path=str(tmp_path / "aof"), fsync=True)
    sub = broker.add_subscriber()
    with pytest.raises(BrokerShutdown):
        thread = threading.Thread(target=broker.begin_shutdown)
        thread.start()
        broker.next_event(sub, timeout=2)
        thread.join()
    broker.close()
