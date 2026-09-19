"""Consumer group semantics: load balancing, isolation, redelivery."""

from minimq import Broker


def test_same_group_load_balancing_no_duplicates(broker):
    broker.create_topic("t")
    for i in range(10):
        broker.publish("t", "m%d" % i)

    c1 = broker.subscribe("t", "g")
    c2 = broker.subscribe("t", "g")
    m1 = c1.poll(5)
    m2 = c2.poll(5)

    offsets1 = {m.offset for m in m1}
    offsets2 = {m.offset for m in m2}
    assert offsets1.isdisjoint(offsets2)
    assert offsets1 | offsets2 == set(range(10))


def test_groups_are_independent(broker):
    broker.create_topic("t")
    for i in range(4):
        broker.publish("t", "m%d" % i)

    ga = broker.subscribe("t", "group-a")
    gb = broker.subscribe("t", "group-b")
    assert [m.offset for m in ga.poll(10)] == [0, 1, 2, 3]
    assert [m.offset for m in gb.poll(10)] == [0, 1, 2, 3]


def test_group_progress_is_tracked_per_group(broker):
    broker.create_topic("t")
    for i in range(4):
        broker.publish("t", "m%d" % i)

    ga = broker.subscribe("t", "group-a")
    for m in ga.poll(2):
        ga.ack(m.offset)

    # group-b has not consumed anything yet.
    gb = broker.subscribe("t", "group-b")
    assert [m.offset for m in gb.poll(10)] == [0, 1, 2, 3]
    # group-a continues where it left off.
    assert [m.offset for m in ga.poll(10)] == [2, 3]


def test_unacked_messages_redelivered_on_repoll(broker):
    broker.create_topic("t")
    broker.publish("t", "a")
    broker.publish("t", "b")

    consumer = broker.subscribe("t", "g")
    first = consumer.poll(2)
    assert [m.body for m in first] == ["a", "b"]
    # No ack: polling again redelivers the same messages.
    second = consumer.poll(2)
    assert [m.body for m in second] == ["a", "b"]
    assert [m.offset for m in second] == [0, 1]


def test_unacked_messages_redelivered_after_reconnect(broker):
    broker.create_topic("t")
    broker.publish("t", "a")

    c1 = broker.subscribe("t", "g")
    assert [m.body for m in c1.poll(1)] == ["a"]
    c1.close()  # disconnect without acking

    c2 = broker.subscribe("t", "g")
    redelivered = c2.poll(1)
    assert [m.body for m in redelivered] == ["a"]
    assert redelivered[0].offset == 0


def test_released_message_goes_to_another_consumer_in_group(broker):
    broker.create_topic("t")
    broker.publish("t", "a")

    c1 = broker.subscribe("t", "g")
    c2 = broker.subscribe("t", "g")
    assert len(c1.poll(1)) == 1
    # While c1 holds the message, c2 must not see it.
    assert c2.poll(1) == []
    c1.close()
    # After c1 disconnects, c2 receives the unacked message.
    assert [m.offset for m in c2.poll(1)] == [0]


def test_acked_message_never_redelivered(broker):
    broker.create_topic("t")
    broker.publish("t", "a")
    c1 = broker.subscribe("t", "g")
    c1.ack(c1.poll(1)[0].offset)
    c1.close()

    c2 = broker.subscribe("t", "g")
    assert c2.poll(1) == []


def test_out_of_order_acks_advance_watermark(broker):
    broker.create_topic("t")
    for i in range(3):
        broker.publish("t", "m%d" % i)
    c = broker.subscribe("t", "g")
    msgs = c.poll(3)
    c.ack(msgs[2].offset)  # ack 2 before 0 and 1
    c.ack(msgs[0].offset)
    c.ack(msgs[1].offset)
    group = broker._groups[("t", "g")]
    assert group.committed == 3
