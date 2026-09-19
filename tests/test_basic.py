"""Basic publish / poll / ack flow and offset semantics."""

import pytest

from minimq import Broker, MqError, Message


@pytest.fixture()
def broker(tmp_path):
    b = Broker(str(tmp_path / "data"))
    b.create_topic("orders")
    yield b
    b.close()


def test_publish_returns_monotonic_offsets_from_zero(broker):
    offsets = [broker.publish("orders", f"m{i}") for i in range(5)]
    assert offsets == [0, 1, 2, 3, 4]
    info = broker.topic_info("orders")
    assert info["earliest_offset"] == 0
    assert info["latest_offset"] == 4
    assert info["next_offset"] == 5
    assert info["message_count"] == 5


def test_poll_returns_message_objects_with_bytes(broker):
    broker.publish("orders", b"\x00\x01binary")
    broker.publish("orders", "text")
    c = broker.subscribe("orders", "g")
    msgs = c.poll(10)
    assert len(msgs) == 2
    assert all(isinstance(m, Message) for m in msgs)
    assert msgs[0].offset == 0 and msgs[0].value == b"\x00\x01binary"
    assert msgs[1].offset == 1 and msgs[1].value == b"text"


def test_poll_respects_max_messages(broker):
    for i in range(5):
        broker.publish("orders", str(i))
    c = broker.subscribe("orders", "g")
    assert [m.offset for m in c.poll(2)] == [0, 1]
    # inflight offsets are skipped, polling continues past them
    assert [m.offset for m in c.poll(2)] == [2, 3]
    assert [m.offset for m in c.poll(2)] == [4]
    for o in range(5):
        c.ack(o)
    assert c.poll(2) == []


def test_poll_empty_topic(broker):
    c = broker.subscribe("orders", "g")
    assert c.poll(5) == []


def test_ack_then_poll_skips_acked(broker):
    for i in range(3):
        broker.publish("orders", str(i))
    c = broker.subscribe("orders", "g")
    for m in c.poll(10):
        c.ack(m.offset)
    assert c.poll(10) == []
    # a later publish is delivered
    broker.publish("orders", "new")
    assert [m.offset for m in c.poll(10)] == [3]


def test_consume_is_alias_for_ack(broker):
    broker.publish("orders", "x")
    c = broker.subscribe("orders", "g")
    m = c.poll(1)[0]
    assert c.consume(m.offset) == m.offset
    assert c.poll(10) == []


def test_out_of_order_acks_leave_gap(broker):
    for i in range(5):
        broker.publish("orders", str(i))
    c = broker.subscribe("orders", "g")
    c.poll(10)
    c.ack(1)
    c.ack(3)
    hwm, gaps = broker.group_progress("orders", "g")
    assert hwm == 0
    assert gaps == [1, 3]
    c.ack(0)
    hwm, gaps = broker.group_progress("orders", "g")
    assert hwm == 2
    assert gaps == [3]
    c.ack(2)
    hwm, gaps = broker.group_progress("orders", "g")
    assert hwm == 4
    assert gaps == []
