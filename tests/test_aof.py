"""Persistence: AOF append, replay on restart, sequence continuity, FLUSH."""

import os

from conftest import ServerHandle, recv_all


def test_aof_file_written(tmp_path):
    aof = str(tmp_path / ".broker.aof")
    h = ServerHandle(aof_path=aof)
    c = h.connect()
    c.publish("t", "hello")
    c.publish("t", "world")
    h.stop()
    c.close()
    data = open(aof, "rb").read()
    assert data.startswith(b"AOF1 1 ")
    assert b"AOF1 2 " in data
    assert b"hello" in data and b"world" in data


def test_restart_recovers_messages_and_seq(tmp_path):
    aof = str(tmp_path / ".broker.aof")
    h1 = ServerHandle(aof_path=aof)
    c1 = h1.connect()
    assert c1.publish("alpha", "m1") == 1
    assert c1.publish("beta", "m2") == 2
    assert c1.publish("alpha", "m3") == 3
    h1.stop()
    c1.close()

    h2 = ServerHandle(aof_path=aof)
    stats_client = h2.connect()
    stats = stats_client.stats()
    assert stats["last_seq"] == 3  # sequence continues, not restarted
    assert stats["topics"] == {"alpha": 2, "beta": 1}

    sub = h2.connect()
    sub.subscribe("alpha")
    msgs = recv_all(sub, 2)
    assert [(m.seq, m.payload) for m in msgs] == [(1, b"m1"), (3, b"m3")]

    # new publishes continue the global sequence
    assert stats_client.publish("alpha", "m4") == 4
    msg = sub.next_message(timeout=2)
    assert (msg.seq, msg.payload) == (4, b"m4")
    h2.stop()
    stats_client.close()
    sub.close()


def test_flush_truncates_aof_and_keeps_seq_checkpoint(tmp_path):
    aof = str(tmp_path / ".broker.aof")
    h1 = ServerHandle(aof_path=aof)
    c = h1.connect()
    c.publish("t", "x")
    c.publish("t", "y")
    c.flush()
    assert os.path.getsize(aof) < 32  # only the #SEQ checkpoint remains
    h1.stop()
    c.close()

    h2 = ServerHandle(aof_path=aof)
    c2 = h2.connect()
    stats = c2.stats()
    assert stats["topics"] == {}
    assert stats["last_seq"] == 2  # monotonic across flush + restart
    assert c2.publish("t", "z") == 3
    h2.stop()
    c2.close()


def test_aof_order_matches_publish_order(tmp_path):
    aof = str(tmp_path / ".broker.aof")
    h = ServerHandle(aof_path=aof)
    c = h.connect()
    for i in range(20):
        c.publish("t", "msg-%d" % i)
    h.stop()
    c.close()

    from minibroker.aof import replay_aof

    records, floor = replay_aof(aof)
    assert floor == 0
    assert [r[0] for r in records] == list(range(1, 21))
    assert [r[2] for r in records] == [b"msg-%d" % i for i in range(20)]


def test_replay_tolerates_torn_tail(tmp_path):
    aof = str(tmp_path / ".broker.aof")
    h = ServerHandle(aof_path=aof)
    c = h.connect()
    c.publish("t", "good-1")
    c.publish("t", "good-2")
    h.stop()
    c.close()
    # simulate a crash mid-write
    with open(aof, "ab") as f:
        f.write(b"AOF1 3 1 100\ntpartial")

    h2 = ServerHandle(aof_path=aof)
    c2 = h2.connect()
    assert c2.stats()["last_seq"] == 2
    sub = h2.connect()
    sub.subscribe("t")
    msgs = recv_all(sub, 2)
    assert [m.payload for m in msgs] == [b"good-1", b"good-2"]
    h2.stop()
    c2.close()
    sub.close()


def test_no_aof_mode(tmp_path):
    h = ServerHandle(aof_path=None)
    c = h.connect()
    c.publish("t", "x")
    assert c.stats()["last_seq"] == 1
    h.stop()
    c.close()
    assert not (tmp_path / ".broker.aof").exists()
