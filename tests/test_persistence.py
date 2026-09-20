import fcntl
import os

import pytest

from minibroker import protocol
from minibroker.exceptions import PersistenceError
from minibroker.persistence import AppendOnlyLog
from minibroker.broker import Broker


def test_aof_records_and_replays_contiguous_messages(tmp_path):
    path = tmp_path / "broker.aof"
    first = Broker(str(path), retention=10)
    first.publish(b"a", b"one")
    first.publish(b"b", b"two\r\n")
    first.close()

    second = Broker(str(path), retention=10)
    assert second.stats()["next_sequence"] == 3
    message = second.publish(b"a", b"three")
    assert message.sequence == 3
    second.close()

    data = path.read_bytes()
    parsed = []
    import io
    reader = io.BytesIO(data)
    while reader.tell() < len(data):
        parsed.append(protocol.read_frame(reader, max_size=None))
    assert parsed[0] == [b"MSG", b"1", b"a", b"one"]
    assert parsed[2] == [b"MSG", b"3", b"a", b"three"]


def test_aof_retention_restores_only_retained_window(tmp_path):
    path = tmp_path / "window.aof"
    first = Broker(str(path), retention=2)
    for idx in range(5):
        first.publish(b"t", str(idx).encode())
    first.close()

    # AOF contains all five publishes, but broker memory only retains last 2.
    second = Broker(str(path), retention=2)
    assert second.stats()["next_sequence"] == 6
    from tests.conftest import FakeConnection
    conn = FakeConnection()
    second.register_connection(conn)
    second.subscribe(conn, b"t")
    assert [m.payload for m in conn.pop_all()] == [b"3", b"4"]
    second.close()


def test_flush_truncates_aof_and_resets_sequence(tmp_path):
    path = tmp_path / "flush.aof"
    broker = Broker(str(path), retention=10)
    broker.publish(b"t", b"old")
    broker.flush()
    assert path.read_bytes() == b""
    broker.close()

    restarted = Broker(str(path), retention=10)
    assert restarted.stats()["next_sequence"] == 1
    message = restarted.publish(b"t", b"new")
    assert message.sequence == 1
    restarted.close()


def test_truncated_trailing_aof_record_is_dropped(tmp_path):
    path = tmp_path / "partial.aof"
    broker = Broker(str(path), retention=10)
    broker.publish(b"t", b"good")
    broker.close()
    good_size = path.stat().st_size
    path.write_bytes(path.read_bytes() + protocol.encode_frame([b"MSG", b"2", b"t", b"bad"])[:5])
    restored = Broker(str(path), retention=10)
    assert restored.stats()["next_sequence"] == 2
    restored.close()
    assert path.stat().st_size == good_size


def test_corrupt_aof_is_not_silently_ignored(tmp_path):
    path = tmp_path / "corrupt.aof"
    path.write_bytes(b"garbage-not-a-frame\n")
    with pytest.raises(PersistenceError):
        Broker(str(path))


def test_two_brokers_cannot_share_aof(tmp_path):
    path = tmp_path / "locked.aof"
    first = Broker(str(path))
    with pytest.raises(PersistenceError):
        Broker(str(path))
    first.close()
