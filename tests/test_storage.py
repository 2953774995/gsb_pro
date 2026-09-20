import pytest

from linebus.broker import Broker, InvalidTopic, QueueFull
from linebus.storage import topic_matches, validate_topic


@pytest.mark.parametrize(
    "topic",
    ["", " ", "\t", "a\nb", "a\x00b", " leading", "trailing ", "a/b/*extra", "/*"],
)
def test_invalid_topics(topic):
    with pytest.raises(ValueError):
        validate_topic(topic)


def test_valid_topic_allows_internal_space():
    assert validate_topic("camera line/1") == "camera line/1"


@pytest.mark.parametrize(
    "pattern,topic,expected",
    [
        ("a", "a", True),
        ("a", "b", False),
        ("line/*", "line/1", True),
        ("line/*", "line/1/sub", False),
        ("line/*", "other/1", False),
        ("line/a/*", "line/a/1", True),
        ("line/a/*", "line/b/1", False),
    ],
)
def test_wildcard_matching(pattern, topic, expected):
    validate_topic(pattern, allow_wildcard=True)
    assert topic_matches(pattern, topic) is expected


def test_broker_fanout_and_independent_outboxes():
    broker = Broker(retention=0)
    a = broker.create_outbox()
    b = broker.create_outbox()
    broker.subscribe(a, "x")
    broker.subscribe(b, "x")
    event = broker.publish("x", b"v")
    assert [o.get(timeout=0.01) for o in (a, b)] == [
        b"EVENT 1 x 1\nv\n",
        b"EVENT 1 x 1\nv\n",
    ]
    assert event.sequence == 1
    broker.remove_connection(a)
    event2 = broker.publish("x", b"w")
    assert event2.sequence == 2
    assert b.get(timeout=0.01) == b"EVENT 2 x 1\nw\n"


def test_retain_default_before_subscribe_and_eviction():
    broker = Broker(retention=3)
    for i in range(4):
        broker.publish("x", str(i).encode())
    outbox = broker.create_outbox()
    broker.subscribe(outbox, "x")
    sequences = []
    while True:
        frame = outbox.get(timeout=0.01)
        if frame is None:
            break
        sequences.append(frame)
    assert sequences == [
        b"EVENT 2 x 1\n1\n",
        b"EVENT 3 x 1\n2\n",
        b"EVENT 4 x 1\n3\n",
    ]


def test_retention_zero_discards_before_subscribe():
    broker = Broker(retention=0)
    broker.publish("x", b"old")
    outbox = broker.create_outbox()
    broker.subscribe(outbox, "x")
    assert outbox.get(timeout=0.01) is None
    broker.publish("x", b"new")
    assert outbox.get(timeout=0.01) == b"EVENT 2 x 3\nnew\n"


def test_reject_full_queue():
    broker = Broker(retention=0, queue_capacity=1, full_strategy="reject")
    outbox = broker.create_outbox()
    broker.subscribe(outbox, "x")
    broker.publish("x", b"a")
    with pytest.raises(QueueFull):
        broker.publish("x", b"b")
    frame = outbox.get(timeout=0.01)
    assert frame == b"EVENT 1 x 1\na\n"


def test_block_full_queue_preserves_order():
    broker = Broker(retention=0, queue_capacity=1, full_strategy="block")
    outbox = broker.create_outbox()
    broker.subscribe(outbox, "x")
    broker.publish("x", b"a")
    result = []

    def publish_b():
        result.append(broker.publish("x", b"b").sequence)

    thread = __import__("threading").Thread(target=publish_b)
    thread.start()
    assert outbox.get(timeout=1) == b"EVENT 1 x 1\na\n"
    thread.join(2)
    assert result == [2]
    assert outbox.get(timeout=1) == b"EVENT 2 x 1\nb\n"


def test_invalid_topic_broker_error():
    broker = Broker()
    outbox = broker.create_outbox()
    with pytest.raises(InvalidTopic):
        broker.publish("", b"x")
    with pytest.raises(InvalidTopic):
        broker.subscribe(outbox, "a\nb")


def test_global_sequence_monotonic_across_topics():
    broker = Broker(retention=0)
    outbox = broker.create_outbox()
    broker.subscribe(outbox, "x/*")
    for topic in ["x/a", "x/b", "x/c"]:
        broker.publish(topic, b"v")
    sequences = []
    for _ in range(3):
        frame = outbox.get(timeout=0.1)
        sequences.append(frame.split(b" ")[1])
    assert sequences == [b"1", b"2", b"3"]


def test_wildcard_backfill_and_live_events():
    broker = Broker(retention=10)
    broker.publish("x/a", b"old-a")
    broker.publish("y/a", b"other")
    outbox = broker.create_outbox()
    broker.subscribe(outbox, "x/*")
    broker.publish("x/b", b"new-b")
    frames = []
    for _ in range(2):
        frames.append(outbox.get(timeout=0.1))
    assert frames == [b"EVENT 1 x/a 5\nold-a\n", b"EVENT 3 x/b 5\nnew-b\n"]


def test_overlapping_subscriptions_do_not_duplicate():
    broker = Broker(retention=10)
    broker.publish("x/a", b"v")
    outbox = broker.create_outbox()
    broker.subscribe(outbox, "x/*")
    broker.subscribe(outbox, "x/a")
    broker.publish("x/a", b"w")
    assert outbox.get(timeout=0.1) == b"EVENT 1 x/a 1\nv\n"
    assert outbox.get(timeout=0.1) == b"EVENT 2 x/a 1\nw\n"
    assert outbox.get(timeout=0.01) is None
