"""Unacknowledged messages must be redelivered."""

import pytest

from minimq import Broker


@pytest.fixture()
def broker(tmp_path):
    b = Broker(str(tmp_path / "data"))
    b.create_topic("t")
    for i in range(4):
        b.publish("t", f"m{i}")
    yield b
    b.close()


def test_released_inflight_is_redelivered_to_other_consumer(broker):
    c1 = broker.subscribe("t", "grp")
    c2 = broker.subscribe("t", "grp")
    got = [m.offset for m in c1.poll(4)]
    assert got == [0, 1, 2, 3]
    assert c2.poll(4) == []
    # c1 crashes without acking: closing returns its inflight leases.
    c1.close()
    assert [m.offset for m in c2.poll(4)] == [0, 1, 2, 3]


def test_partial_ack_then_redelivery(broker):
    c1 = broker.subscribe("t", "grp")
    c2 = broker.subscribe("t", "grp")
    msgs = c1.poll(4)
    c1.ack(msgs[0].offset)  # 0 acked
    c1.ack(msgs[2].offset)  # 2 gap-acked
    c1.close()
    redelivered = [m.offset for m in c2.poll(4)]
    assert redelivered == [1, 3]


def test_redelivery_after_broker_restart(tmp_path):
    data = str(tmp_path / "data")
    b = Broker(data)
    b.create_topic("t")
    for i in range(4):
        b.publish("t", f"m{i}")
    c = b.subscribe("t", "grp")
    msgs = c.poll(4)
    c.ack(msgs[0].offset)
    c.close()
    b.close()

    b2 = Broker(data)
    c2 = b2.subscribe("t", "grp")
    got = [m.offset for m in c2.poll(10)]
    assert got == [1, 2, 3]
    b2.close()
