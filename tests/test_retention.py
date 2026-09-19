"""Retention policy: old messages dropped, consumer offsets stay correct."""

from minimq import Broker, MqError


def test_max_messages_drops_oldest(tmp_path):
    b = Broker(str(tmp_path / "d"))
    b.create_topic("t", max_messages=3)
    for i in range(7):
        b.publish("t", "m{}".format(i))
    info = b.topic_info("t")
    assert info["message_count"] == 3
    assert info["earliest_offset"] == 4
    assert info["latest_offset"] == 6
    assert info["next_offset"] == 7
    b.close()


def test_max_bytes_drops_oldest(tmp_path):
    b = Broker(str(tmp_path / "d"))
    b.create_topic("t", max_bytes=10)
    for i in range(5):
        b.publish("t", "xxxx")  # 4 bytes each -> keep at most 2
    info = b.topic_info("t")
    assert info["earliest_offset"] == 3
    assert info["message_count"] == 2
    assert info["size_bytes"] == 8
    b.close()


def test_fresh_consumer_only_sees_retained_window(tmp_path):
    b = Broker(str(tmp_path / "d"))
    b.create_topic("t", max_messages=2)
    for i in range(5):
        b.publish("t", str(i))
    c = b.subscribe("t", "g")
    assert [m.offset for m in c.poll(10)] == [3, 4]
    b.close()


def test_acked_group_advances_past_evicted_offsets(tmp_path):
    b = Broker(str(tmp_path / "d"))
    b.create_topic("t", max_messages=3)
    c = b.subscribe("t", "g")
    for i in range(3):
        b.publish("t", str(i))
    msgs = c.poll(3)
    c.ack(msgs[0].offset)  # only ack 0; 1,2 inflight
    # eviction removes offsets 0..2 as 4,5,6 arrive
    for i in range(3, 7):
        b.publish("t", str(i))
    hwm, gaps = b.group_progress("t", "g")
    # watermark advances as retained history moves; evicted inflight
    # leases (1, 2) and the never-delivered 3 are all safely behind it
    assert hwm == 4
    assert gaps == []
    # messages still inside the retention window can be delivered normally
    assert [m.offset for m in c.poll(10)] == [4, 5, 6]
    b.close()


def test_retention_state_correct_after_restart(tmp_path):
    data = str(tmp_path / "data")
    b = Broker(data)
    b.create_topic("t", max_messages=2)
    c = b.subscribe("t", "g")
    for i in range(5):
        b.publish("t", str(i))
    msgs = c.poll(2)
    assert [m.offset for m in msgs] == [3, 4]
    c.ack(3)
    c.ack(4)
    c.close()
    b.close()

    b2 = Broker(data)
    assert b2.topic_info("t")["message_count"] == 2
    c2 = b2.subscribe("t", "g")
    assert c2.poll(10) == []  # nothing redelivered after restart
    b2.close()


def test_ack_evicted_offset_raises(tmp_path):
    b = Broker(str(tmp_path / "d"))
    b.create_topic("t", max_messages=1)
    c = b.subscribe("t", "g")
    b.publish("t", "a")
    c.poll(1)
    b.publish("t", "b")  # evicts 0
    try:
        c.ack(0)
    except MqError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected MqError acking evicted offset")
    b.close()


def test_retention_invalid_config_raises():
    from minimq import RetentionPolicy
    try:
        RetentionPolicy(max_messages=0)
    except MqError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected MqError for max_messages=0")


def test_retention_rewrites_log_file(tmp_path):
    data = str(tmp_path / "d")
    b = Broker(data)
    b.create_topic("t", max_messages=2)
    for i in range(6):
        b.publish("t", "m{}".format(i))
    b.close()
    b2 = Broker(data)
    c = b2.subscribe("t", "fresh")
    assert [m.value for m in c.poll(10)] == [b"m4", b"m5"]
    b2.close()
