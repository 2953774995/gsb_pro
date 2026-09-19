"""Basic publish / poll / ack flows."""

import pytest

from minimq import MqError


def test_publish_assigns_monotonic_offsets_from_zero(broker):
    broker.create_topic("t")
    offsets = [broker.publish("t", "m%d" % i) for i in range(5)]
    assert offsets == [0, 1, 2, 3, 4]


def test_publish_poll_ack_roundtrip(broker):
    broker.create_topic("t")
    broker.publish("t", "hello")
    broker.publish("t", "world")

    consumer = broker.subscribe("t", "g")
    msgs = consumer.poll(10)
    assert [m.body for m in msgs] == ["hello", "world"]
    assert [m.offset for m in msgs] == [0, 1]
    assert all(m.topic == "t" for m in msgs)

    consumer.ack(0)
    consumer.ack(1)
    # Everything acked: nothing left to consume.
    assert consumer.poll(10) == []


def test_poll_respects_max_messages(broker):
    broker.create_topic("t")
    for i in range(5):
        broker.publish("t", "m%d" % i)
    consumer = broker.subscribe("t", "g")
    msgs = consumer.poll(2)
    assert len(msgs) == 2
    assert [m.offset for m in msgs] == [0, 1]


def test_poll_empty_topic_returns_empty_list(broker):
    broker.create_topic("t")
    consumer = broker.subscribe("t", "g")
    assert consumer.poll(5) == []


def test_offsets_keep_increasing_after_retention(broker):
    broker.create_topic("t", max_messages=3)
    for i in range(6):
        broker.publish("t", "m%d" % i)
    # Next offset must not rewind even though old messages were dropped.
    assert broker.publish("t", "m6") == 6


def test_bytes_message_is_accepted(broker):
    broker.create_topic("t")
    broker.publish("t", "hello bytes".encode("utf-8"))
    consumer = broker.subscribe("t", "g")
    assert consumer.poll(1)[0].body == "hello bytes"
