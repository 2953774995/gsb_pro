"""Retention policies: max messages / max bytes, offset semantics."""

from minimq import Broker


def test_max_messages_drops_oldest(broker):
    broker.create_topic("t", max_messages=3)
    for i in range(6):
        broker.publish("t", "m%d" % i)
    info = broker.list_topics()[0]
    assert info["messages"] == 3
    assert info["base_offset"] == 3
    assert info["next_offset"] == 6

    consumer = broker.subscribe("t", "g")
    assert [m.offset for m in consumer.poll(10)] == [3, 4, 5]


def test_max_bytes_drops_oldest(broker):
    broker.create_topic("t", max_bytes=10)  # each message is 4 bytes
    for i in range(5):
        broker.publish("t", "m%03d" % i)
    info = broker.list_topics()[0]
    assert info["messages"] == 2  # 2 * 4 bytes <= 10
    consumer = broker.subscribe("t", "g")
    assert [m.offset for m in consumer.poll(10)] == [3, 4]


def test_retention_keeps_at_least_one_message(broker):
    broker.create_topic("t", max_bytes=1)
    broker.publish("t", "this is way bigger than one byte")
    assert broker.list_topics()[0]["messages"] == 1


def test_retention_applies_to_disk_log(tmp_path):
    data_dir = str(tmp_path / "mq")
    b = Broker(data_dir=data_dir)
    b.create_topic("t", max_messages=2)
    for i in range(5):
        b.publish("t", "m%d" % i)
    b.close()

    b2 = Broker(data_dir=data_dir)
    consumer = b2.subscribe("t", "g")
    # Dropped messages must not reappear after a restart.
    assert [m.offset for m in consumer.poll(10)] == [3, 4]
    b2.close()


def test_lagging_consumer_is_clamped_to_base_offset(broker):
    broker.create_topic("t", max_messages=2)
    consumer = broker.subscribe("t", "g")
    for i in range(5):
        broker.publish("t", "m%d" % i)
    # The consumer never polled; offsets 0-2 are gone. It must start at 3
    # instead of crashing or rewinding.
    assert [m.offset for m in consumer.poll(10)] == [3, 4]
