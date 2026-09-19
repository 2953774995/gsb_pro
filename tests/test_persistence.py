"""On-disk recovery: messages, offsets and torn-tail truncation."""

import json
import os
import struct
import zlib

from minimq import Broker
from minimq.storage import MAGIC, _HEADER, _CRC


def log_path(data_dir, topic):
    return os.path.join(data_dir, "logs", topic + ".log")


def test_messages_and_offsets_survive_restart(tmp_path):
    data = str(tmp_path / "data")
    b = Broker(data)
    b.create_topic("t")
    for i in range(5):
        b.publish("t", "msg-{}".format(i))
    c = b.subscribe("t", "g")
    c.poll(5)
    c.ack(0)
    c.ack(1)
    c.close()
    b.close()

    b2 = Broker(data)
    info = b2.topic_info("t")
    assert info["message_count"] == 5
    assert info["next_offset"] == 5
    c2 = b2.subscribe("t", "g")
    assert [m.offset for m in c2.poll(10)] == [2, 3, 4]
    hwm, gaps = b2.group_progress("t", "g")
    assert hwm == 2 and gaps == []
    b2.close()


def test_acked_offsets_not_redelivered_after_restart(tmp_path):
    data = str(tmp_path / "data")
    b = Broker(data)
    b.create_topic("t")
    for i in range(3):
        b.publish("t", str(i))
    c = b.subscribe("t", "g")
    for m in c.poll(10):
        c.ack(m.offset)
    c.close()
    b.close()

    b2 = Broker(data)
    c2 = b2.subscribe("t", "g")
    assert c2.poll(10) == []
    b2.publish("t", "after-restart")
    assert [m.offset for m in c2.poll(10)] == [3]
    b2.close()


def test_gap_acked_offsets_survive_restart(tmp_path):
    data = str(tmp_path / "data")
    b = Broker(data)
    b.create_topic("t")
    for i in range(5):
        b.publish("t", str(i))
    c = b.subscribe("t", "g")
    c.poll(10)
    c.ack(1)
    c.ack(4)
    c.close()
    b.close()

    b2 = Broker(data)
    c2 = b2.subscribe("t", "g")
    assert [m.offset for m in c2.poll(10)] == [0, 2, 3]
    hwm, gaps = b2.group_progress("t", "g")
    assert hwm == 0 and gaps == [1, 4]
    b2.close()


def _append_raw_record(fh, offset, payload, magic=MAGIC):
    body = _HEADER.pack(magic, len(payload), offset) + payload
    fh.write(body + _CRC.pack(zlib.crc32(body) & 0xFFFFFFFF))


def test_torn_tail_record_is_truncated(tmp_path):
    data = str(tmp_path / "data")
    b = Broker(data)
    b.create_topic("t")
    b.publish("t", "good-0")
    b.publish("t", "good-1")
    b.close()

    path = log_path(data, "t")
    size_before = os.path.getsize(path)
    # Simulate a torn write: append a partial header + partial payload.
    with open(path, "ab") as f:
        f.write(struct.pack(">BIQ", MAGIC, 100, 2)[:4])  # cut header
        f.write(b"partial")
    assert os.path.getsize(path) > size_before

    b2 = Broker(data)
    info = b2.topic_info("t")
    assert info["message_count"] == 2
    assert info["next_offset"] == 2
    # file must have been truncated back to the valid prefix
    assert os.path.getsize(path) == size_before
    # broker stays usable and appends align to the next offset
    assert b2.publish("t", "after-torn") == 2
    b2.close()

    b3 = Broker(data)
    assert b3.topic_info("t")["message_count"] == 3
    b3.close()


def test_corrupt_checksum_tail_is_truncated(tmp_path):
    data = str(tmp_path / "data")
    b = Broker(data)
    b.create_topic("t")
    b.publish("t", "ok")
    b.close()

    path = log_path(data, "t")
    with open(path, "ab") as f:
        body = _HEADER.pack(MAGIC, 4, 1) + b"evil"
        f.write(body + _CRC.pack(0xDEADBEEF))  # bad checksum

    b2 = Broker(data)
    assert b2.topic_info("t")["message_count"] == 1
    assert b2.publish("t", "fixed") == 1
    b2.close()


def test_bad_magic_tail_is_truncated(tmp_path):
    data = str(tmp_path / "data")
    b = Broker(data)
    b.create_topic("t")
    b.publish("t", "ok")
    b.close()

    path = log_path(data, "t")
    with open(path, "ab") as f:
        _append_raw_record(f, 1, b"x", magic=0x58)

    b2 = Broker(data)
    assert b2.topic_info("t")["message_count"] == 1
    b2.close()


def test_topic_metadata_survives_when_no_writes(tmp_path):
    data = str(tmp_path / "data")
    b = Broker(data)
    b.create_topic("empty", max_messages=10)
    b.close()
    b2 = Broker(data)
    assert "empty" in b2.list_topics()
    info = b2.topic_info("empty")
    assert info["retention"]["max_messages"] == 10
    b2.close()


def test_group_state_file_is_json(tmp_path):
    data = str(tmp_path / "data")
    b = Broker(data)
    b.create_topic("t")
    b.publish("t", "a")
    b.publish("t", "b")
    c = b.subscribe("t", "g")
    c.poll(2)
    c.ack(0)
    c.close()
    b.close()
    files = os.listdir(os.path.join(data, "groups"))
    assert len(files) == 1 and files[0].endswith(".json")
    with open(os.path.join(data, "groups", files[0])) as f:
        state = json.load(f)
    assert state == {"hwm": 1, "gaps": []}
