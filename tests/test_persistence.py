"""AOF persistence and restart recovery."""

import os

from minibroker.persistence import AOF_MAGIC, AppendOnlyLog
from minibroker.storage import Message
from tests.conftest import drain


def test_aof_unit_append_and_recover(tmp_path):
    path = str(tmp_path / "aof")
    aof = AppendOnlyLog(path)
    aof.open_for_append()
    messages = [
        Message(1, "t", b""),
        Message(2, "t", b"line1\nline2\t\xff"),
        Message(3, "u/2", b"third"),
    ]
    for msg in messages:
        aof.append_message(msg)
    aof.close()

    recovered, max_seq = AppendOnlyLog.recover(path)
    assert recovered == messages
    assert max_seq == 3
    with open(path, "rb") as handle:
        assert handle.read().startswith(AOF_MAGIC)


def test_aof_truncate_forgets_everything(tmp_path):
    path = str(tmp_path / "aof")
    aof = AppendOnlyLog(path)
    aof.open_for_append()
    aof.append_message(Message(1, "t", b"x"))
    aof.truncate()
    aof.append_message(Message(2, "t", b"y"))
    aof.close()
    recovered, max_seq = AppendOnlyLog.recover(path)
    assert recovered == [Message(2, "t", b"y")]
    assert max_seq == 2


def test_truncated_trailing_frame_is_ignored(tmp_path):
    path = str(tmp_path / "aof")
    aof = AppendOnlyLog(path)
    aof.open_for_append()
    aof.append_message(Message(1, "t", b"good"))
    aof.close()
    with open(path, "ab") as handle:
        handle.write(b"P 2 1 10\ntpartial")  # header + partial body
    recovered, max_seq = AppendOnlyLog.recover(path)
    assert recovered == [Message(1, "t", b"good")]
    assert max_seq == 1


def test_messages_survive_restart_with_sequence_continuity(harness, aof_path):
    pub = harness.client()
    sub = harness.client()
    sub.subscribe("t")
    for i in range(5):
        pub.publish("t", b"m%d" % i)
    drain(sub, 5)
    sub.close()
    pub.close()

    restarted = harness.restart()
    try:
        client = restarted.client()
        client.subscribe("t")
        msgs = drain(client, 5)
        assert [(m[1], m[2]) for m in msgs] == [
            (i + 1, b"m%d" % i) for i in range(5)
        ]
        # sequence counter continues after recovery
        seq = client.publish("t", b"after")
        assert seq == 6
        assert client.next_message(2)[2] == b"after"
        client.close()
    finally:
        restarted.stop()


def test_aof_preserves_binary_payloads_across_restart(harness):
    pub = harness.client()
    blob = b"\x00\x01\x02\n\r\n\t\xff spaced"
    pub.publish("bin", blob)
    pub.close()

    restarted = harness.restart()
    try:
        client = restarted.client()
        client.subscribe("bin")
        msg = client.next_message(2)
        assert msg is not None and msg[2] == blob
        client.close()
    finally:
        restarted.stop()


def test_flush_clears_memory_and_aof(harness, aof_path):
    pub = harness.client()
    pub.publish("t", b"before")
    pub.flush()

    assert os.path.getsize(aof_path) == len(AOF_MAGIC)

    sub = harness.client()
    sub.subscribe("t")
    assert sub.next_message(timeout=0.3) is None

    # sequence is reset after flush
    assert pub.publish("t", b"fresh") == 1
    assert sub.next_message(2) == ("t", 1, b"fresh")

    restarted = harness.restart()
    try:
        client = restarted.client()
        client.subscribe("t")
        # only the post-flush message survived
        assert client.next_message(2) == ("t", 1, b"fresh")
        assert client.publish("t", b"again") == 2
        client.close()
    finally:
        restarted.stop()
