from pathlib import Path

import pytest

from linebus.aof import AOFError, AppendOnlyLog, MAGIC
from linebus.broker import Broker
from linebus.storage import Event


def test_aof_records_sequence_topic_arbitrary_payload(tmp_path):
    path = tmp_path / "aof"
    aof = AppendOnlyLog(path)
    aof.initialize()
    aof.append(Event(1, "camera line/a", b"v\n \t\x00"))
    aof.append(Event(2, "cam/b", b""))
    aof.close()

    data = path.read_bytes()
    assert data.startswith(MAGIC)
    events, next_sequence = AppendOnlyLog.load(path)
    assert [(e.sequence, e.topic, e.payload) for e in events] == [
        (1, "camera line/a", b"v\n \t\x00"),
        (2, "cam/b", b""),
    ]
    assert next_sequence == 3


def test_broker_restores_aof_with_continuous_sequence(tmp_path):
    path = tmp_path / "aof"
    aof = AppendOnlyLog(path)
    aof.initialize()
    broker = Broker(aof, retention=10)
    broker.publish("a", b"1")
    broker.publish("b", b"2")
    aof.close()

    aof2 = AppendOnlyLog(path)
    aof2.initialize()
    broker2 = Broker(aof2, retention=10)
    broker2.restore()
    outbox = broker2.create_outbox()
    broker2.subscribe(outbox, "a")
    assert outbox.get(timeout=0.1) == b"EVENT 1 a 1\n1\n"
    new_event = broker2.publish("a", b"3")
    assert new_event.sequence == 3
    assert outbox.get(timeout=0.1) == b"EVENT 3 a 1\n3\n"
    aof2.close()


def test_torn_final_record_is_truncated(tmp_path):
    path = tmp_path / "aof"
    aof = AppendOnlyLog(path)
    aof.initialize()
    aof.append(Event(1, "a", b"good"))
    aof.close()
    data = path.read_bytes()
    path.write_bytes(data + b"EVENT 2 a 4\nab")
    events, next_sequence = AppendOnlyLog.load(path)
    assert [e.payload for e in events] == [b"good"]
    assert next_sequence == 2
    # Reload is stable.
    events, next_sequence = AppendOnlyLog.load(path)
    assert next_sequence == 2


def test_corrupt_middle_record_fails(tmp_path):
    path = tmp_path / "aof"
    aof = AppendOnlyLog(path)
    aof.initialize()
    aof.append(Event(1, "a", b"good"))
    aof.append(Event(3, "a", b"bad-seq"))
    aof.close()
    with pytest.raises(AOFError):
        AppendOnlyLog.load(path)


def test_flush_clears_aof_and_resets_sequence(tmp_path):
    path = tmp_path / "aof"
    aof = AppendOnlyLog(path)
    aof.initialize()
    broker = Broker(aof, retention=10)
    broker.publish("a", b"old")
    broker.flush()
    assert broker.stats()["last_sequence"] == 0
    event = broker.publish("a", b"new")
    assert event.sequence == 1
    aof.close()
    events, next_sequence = AppendOnlyLog.load(path)
    assert [e.payload for e in events] == [b"new"]
    assert next_sequence == 2


def test_aof_order_matches_execution_order(tmp_path):
    path = tmp_path / "aof"
    aof = AppendOnlyLog(path)
    aof.initialize()
    broker = Broker(aof, retention=0)
    for i in range(20):
        broker.publish("t", str(i).encode())
    aof.close()
    events, _ = AppendOnlyLog.load(path)
    assert [int(e.payload) for e in events] == list(range(20))
    assert [e.sequence for e in events] == list(range(1, 21))
