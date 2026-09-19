"""Persistence: restart recovery, committed offsets, corrupt tail."""

import os
import struct

import pytest

from minimq import Broker, MqError


def make_broker(data_dir):
    return Broker(data_dir=str(data_dir))


def test_restart_recovers_messages_and_offsets(tmp_path):
    data_dir = tmp_path / "mq"
    b = make_broker(data_dir)
    b.create_topic("t")
    for i in range(5):
        b.publish("t", "m%d" % i)
    b.close()

    b2 = make_broker(data_dir)
    consumer = b2.subscribe("t", "g")
    msgs = consumer.poll(10)
    assert [m.body for m in msgs] == ["m0", "m1", "m2", "m3", "m4"]
    assert [m.offset for m in msgs] == [0, 1, 2, 3, 4]
    # Offsets continue monotonically after restart.
    assert b2.publish("t", "m5") == 5
    b2.close()


def test_committed_offsets_survive_restart(tmp_path):
    data_dir = tmp_path / "mq"
    b = make_broker(data_dir)
    b.create_topic("t")
    for i in range(4):
        b.publish("t", "m%d" % i)
    consumer = b.subscribe("t", "g")
    for m in consumer.poll(2):
        consumer.ack(m.offset)
    b.close()

    b2 = make_broker(data_dir)
    consumer2 = b2.subscribe("t", "g")
    # Offsets 0 and 1 were acked before the restart: only 2,3 come back.
    assert [m.offset for m in consumer2.poll(10)] == [2, 3]
    b2.close()


def test_unacked_messages_redelivered_after_restart(tmp_path):
    data_dir = tmp_path / "mq"
    b = make_broker(data_dir)
    b.create_topic("t")
    b.publish("t", "a")
    consumer = b.subscribe("t", "g")
    assert len(consumer.poll(1)) == 1  # delivered but never acked
    b.close()

    b2 = make_broker(data_dir)
    consumer2 = b2.subscribe("t", "g")
    assert [m.body for m in consumer2.poll(1)] == ["a"]
    b2.close()


def test_groups_do_not_share_committed_state(tmp_path):
    data_dir = tmp_path / "mq"
    b = make_broker(data_dir)
    b.create_topic("t")
    b.publish("t", "a")
    c = b.subscribe("t", "g1")
    c.ack(c.poll(1)[0].offset)
    b.close()

    b2 = make_broker(data_dir)
    assert b2.subscribe("t", "g1").poll(1) == []
    assert len(b2.subscribe("t", "g2").poll(1)) == 1
    b2.close()


def test_corrupt_tail_is_truncated(tmp_path):
    data_dir = tmp_path / "mq"
    b = make_broker(data_dir)
    b.create_topic("t")
    for i in range(3):
        b.publish("t", "m%d" % i)
    b.close()

    log_path = data_dir / "topics" / "t" / "messages.log"
    good_size = log_path.stat().st_size
    # Simulate a crashed write: half of a record appended.
    with open(log_path, "ab") as f:
        f.write(struct.pack(">I", 100) + b"\x00\x00")  # torn header+payload
        f.write(b"garbage-garbage")

    b2 = make_broker(data_dir)  # must not crash
    consumer = b2.subscribe("t", "g")
    assert [m.body for m in consumer.poll(10)] == ["m0", "m1", "m2"]
    # The corrupt tail was truncated...
    assert log_path.stat().st_size == good_size
    # ...and the log is still appendable with correct offsets.
    assert b2.publish("t", "m3") == 3
    b2.close()

    # Everything, including the post-recovery append, survives a restart.
    b3 = make_broker(data_dir)
    assert [m.body for m in b3.subscribe("t", "g2").poll(10)] == [
        "m0", "m1", "m2", "m3"]
    b3.close()


def test_crc_mismatch_is_truncated(tmp_path):
    data_dir = tmp_path / "mq"
    b = make_broker(data_dir)
    b.create_topic("t")
    b.publish("t", "good")
    b.publish("t", "bad")
    b.close()

    log_path = data_dir / "topics" / "t" / "messages.log"
    with open(log_path, "r+b") as f:
        f.seek(-2, os.SEEK_END)
        f.write(b"XX")  # corrupt the 2nd record without fixing its CRC

    b2 = make_broker(data_dir)
    # The corrupt record is dropped; the good one survives.
    assert [m.body for m in b2.subscribe("t", "g").poll(10)] == ["good"]
    assert b2.publish("t", "new") == 1  # offset continues from last good
    b2.close()


def test_retention_config_survives_restart(tmp_path):
    data_dir = tmp_path / "mq"
    b = make_broker(data_dir)
    b.create_topic("t", max_messages=2)
    b.close()

    b2 = make_broker(data_dir)
    for i in range(5):
        b2.publish("t", "m%d" % i)
    consumer = b2.subscribe("t", "g")
    assert [m.offset for m in consumer.poll(10)] == [3, 4]
    b2.close()


def test_in_memory_broker_persists_nothing():
    b = Broker()
    b.create_topic("t")
    b.publish("t", "x")
    b.close()
    with pytest.raises(MqError):
        b.publish("t", "y")
