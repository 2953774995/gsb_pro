"""All expected error conditions must raise MqError (or a subclass)."""

import pytest

from minimq import Broker, MqError
from minimq.errors import (
    ConsumerGroupError,
    MessageTooLargeError,
    TopicExistsError,
    TopicNotFoundError,
)


@pytest.fixture()
def broker(tmp_path):
    b = Broker(str(tmp_path / "d"))
    b.create_topic("t")
    yield b
    b.close()


def test_publish_unknown_topic(broker):
    with pytest.raises(MqError) as ei:
        broker.publish("nope", "x")
    assert isinstance(ei.value, TopicNotFoundError)
    assert "nope" in str(ei.value)


def test_subscribe_unknown_topic(broker):
    with pytest.raises(TopicNotFoundError):
        broker.subscribe("nope", "g")


def test_create_duplicate_topic(broker):
    with pytest.raises(TopicExistsError):
        broker.create_topic("t")


def test_invalid_topic_name(broker):
    with pytest.raises(MqError):
        broker.create_topic("../escape")
    with pytest.raises(MqError):
        broker.create_topic("")


def test_invalid_group_name(broker):
    with pytest.raises(MqError):
        broker.subscribe("t", "bad/group")


def test_oversized_message_rejected(tmp_path):
    b = Broker(str(tmp_path / "d"))
    b.create_topic("small", max_message_size=4)
    with pytest.raises(MessageTooLargeError) as ei:
        b.publish("small", b"12345")
    assert "exceeds" in str(ei.value)
    # nothing was appended
    assert b.topic_info("small")["message_count"] == 0
    b.close()


def test_bad_message_type(broker):
    with pytest.raises(MqError):
        broker.publish("t", 123)


def test_duplicate_ack(broker):
    broker.publish("t", "x")
    c = broker.subscribe("t", "g")
    m = c.poll(1)[0]
    c.ack(m.offset)
    with pytest.raises(ConsumerGroupError) as ei:
        c.ack(m.offset)
    assert "duplicate ack" in str(ei.value)


def test_ack_never_delivered_offset(broker):
    broker.publish("t", "x")
    c = broker.subscribe("t", "g")
    with pytest.raises(ConsumerGroupError) as ei:
        c.ack(0)
    assert "never delivered" in str(ei.value)


def test_ack_future_offset(broker):
    broker.publish("t", "x")
    c = broker.subscribe("t", "g")
    c.poll(1)
    with pytest.raises(MqError):
        c.ack(99)


def test_ack_negative_offset(broker):
    c = broker.subscribe("t", "g")
    with pytest.raises(MqError):
        c.ack(-1)


def test_poll_bad_max_messages(broker):
    c = broker.subscribe("t", "g")
    with pytest.raises(MqError):
        c.poll(0)
    with pytest.raises(MqError):
        c.poll(-3)


def test_close_releases_inflight_and_blocks_use(broker):
    broker.publish("t", "x")
    c = broker.subscribe("t", "g")
    c.poll(1)
    c.close()
    with pytest.raises(MqError):
        c.poll(1)
    with pytest.raises(MqError):
        c.ack(0)
