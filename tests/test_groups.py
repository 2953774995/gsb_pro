"""Consumer group semantics: load balancing and independent groups."""

import pytest

from minimq import Broker


@pytest.fixture()
def broker(tmp_path):
    b = Broker(str(tmp_path / "data"))
    b.create_topic("t")
    for i in range(6):
        b.publish("t", f"m{i}")
    yield b
    b.close()


def test_same_group_consumers_share_messages(broker):
    c1 = broker.subscribe("t", "grp")
    c2 = broker.subscribe("t", "grp")

    first = c1.poll(3)
    second = c2.poll(3)
    offsets = [m.offset for m in first] + [m.offset for m in second]
    assert sorted(offsets) == [0, 1, 2, 3, 4, 5]
    # No overlap and nothing left while everything is inflight.
    assert {m.offset for m in first}.isdisjoint({m.offset for m in second})
    assert c1.poll(10) == [] and c2.poll(10) == []


def test_load_balancing_interleaved_polls(broker):
    consumers = [broker.subscribe("t", "grp") for _ in range(3)]
    seen = []
    # Round-robin polls across consumers.
    for _ in range(6):
        for c in consumers:
            msgs = c.poll(1)
            if msgs:
                seen.append((c.cid, msgs[0].offset))
    assert sorted(o for _, o in seen) == [0, 1, 2, 3, 4, 5]
    assert len({o for _, o in seen}) == 6  # no duplicate delivery


def test_ack_by_other_consumer_rejected(broker):
    c1 = broker.subscribe("t", "grp")
    c2 = broker.subscribe("t", "grp")
    m = c1.poll(1)[0]
    with pytest.raises(Exception):
        c2.ack(m.offset)
    # owner can still ack
    c1.ack(m.offset)


def test_different_groups_each_see_full_stream(broker):
    ga = broker.subscribe("t", "A")
    gb = broker.subscribe("t", "B")
    a = [m.offset for m in ga.poll(10)]
    b = [m.offset for m in gb.poll(10)]
    assert a == [0, 1, 2, 3, 4, 5]
    assert b == [0, 1, 2, 3, 4, 5]
    # acking in A does not affect B
    for o in a:
        ga.ack(o)
    assert ga.poll(10) == []
    assert [m.offset for m in gb.poll(10)] == []  # still inflight on gb
    for m in list(b):
        pass
    gb2 = broker.subscribe("t", "B")
    # gb's messages stay inflight until gb released; check independent progress
    assert broker.group_progress("t", "A")[0] == 6
    assert broker.group_progress("t", "B")[0] == 0


def test_new_group_starts_from_beginning(broker):
    c1 = broker.subscribe("t", "first")
    c1.poll(10)
    for o in range(6):
        c1.ack(o)
    late = broker.subscribe("t", "latecomer")
    assert [m.offset for m in late.poll(10)] == [0, 1, 2, 3, 4, 5]
