"""Error handling: every misuse must raise MqError with a clear message."""

import pytest

from minimq import Broker, MqError


def test_subscribe_to_missing_topic(broker):
    with pytest.raises(MqError, match="does not exist"):
        broker.subscribe("nope", "g")


def test_publish_to_missing_topic(broker):
    with pytest.raises(MqError, match="does not exist"):
        broker.publish("nope", "x")


def test_create_duplicate_topic(broker):
    broker.create_topic("t")
    with pytest.raises(MqError, match="already exists"):
        broker.create_topic("t")


def test_duplicate_ack(broker):
    broker.create_topic("t")
    broker.publish("t", "a")
    c = broker.subscribe("t", "g")
    c.ack(c.poll(1)[0].offset)
    with pytest.raises(MqError, match="not delivered|already acknowledged"):
        c.ack(0)


def test_ack_offset_never_delivered(broker):
    broker.create_topic("t")
    broker.publish("t", "a")
    c = broker.subscribe("t", "g")
    with pytest.raises(MqError, match="not delivered"):
        c.ack(0)


def test_ack_offset_owned_by_another_consumer(broker):
    broker.create_topic("t")
    broker.publish("t", "a")
    c1 = broker.subscribe("t", "g")
    c2 = broker.subscribe("t", "g")
    offset = c1.poll(1)[0].offset
    with pytest.raises(MqError, match="another consumer"):
        c2.ack(offset)


def test_oversized_message_rejected(tmp_path):
    b = Broker(data_dir=str(tmp_path / "mq"), max_message_bytes=16)
    b.create_topic("t")
    with pytest.raises(MqError, match="exceeds the limit"):
        b.publish("t", "x" * 17)
    b.publish("t", "x" * 16)  # exactly at the limit is fine
    b.close()


def test_invalid_message_type(broker):
    broker.create_topic("t")
    with pytest.raises(MqError, match="str or bytes"):
        broker.publish("t", 123)


def test_invalid_topic_name(broker):
    with pytest.raises(MqError, match="invalid topic name"):
        broker.create_topic("bad/name")
    with pytest.raises(MqError, match="non-empty"):
        broker.create_topic("")


def test_invalid_group_name(broker):
    broker.create_topic("t")
    with pytest.raises(MqError, match="invalid group name"):
        broker.subscribe("t", "bad group")


def test_invalid_retention_config(broker):
    with pytest.raises(MqError, match="max_messages"):
        broker.create_topic("t", max_messages=0)


def test_poll_with_invalid_max_messages(broker):
    broker.create_topic("t")
    c = broker.subscribe("t", "g")
    with pytest.raises(MqError, match="max_messages"):
        c.poll(0)


def test_closed_consumer_raises(broker):
    broker.create_topic("t")
    c = broker.subscribe("t", "g")
    c.close()
    with pytest.raises(MqError, match="closed"):
        c.poll(1)
    with pytest.raises(MqError, match="closed"):
        c.ack(0)


def test_closed_broker_raises(broker):
    broker.create_topic("t")
    broker.close()
    with pytest.raises(MqError, match="closed"):
        broker.publish("t", "x")
