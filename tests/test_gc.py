"""Consumers forgotten without close() must not pin messages forever."""

import gc

from minimq import Broker


def test_garbage_collected_consumer_releases_inflight(tmp_path):
    b = Broker(str(tmp_path / "d"))
    b.create_topic("t")
    b.publish("t", "x")

    c1 = b.subscribe("t", "g")
    assert [m.offset for m in c1.poll(1)] == [0]
    del c1
    gc.collect()  # finalizer releases the inflight lease

    c2 = b.subscribe("t", "g")
    assert [m.offset for m in c2.poll(1)] == [0]
    b.close()
