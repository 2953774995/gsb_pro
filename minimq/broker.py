"""Broker: manages topics, consumer groups and concurrent access."""

import os
import re
import threading
import uuid
from dataclasses import dataclass
from typing import List

from .errors import MqError
from .group import ConsumerGroup
from .topic import Topic

_NAME_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")
DEFAULT_MAX_MESSAGE_BYTES = 1024 * 1024  # 1 MiB


@dataclass(frozen=True)
class Message:
    """A single message delivered to a consumer."""
    topic: str
    offset: int
    body: str


def _validate_name(kind, name):
    if not isinstance(name, str) or not name:
        raise MqError("%s name must be a non-empty string" % kind)
    if not _NAME_RE.match(name):
        raise MqError(
            "invalid %s name %r: only letters, digits, '_', '-', '.' "
            "are allowed" % (kind, name))


class Broker(object):
    """A mini in-memory message broker with optional disk persistence.

    Parameters:
        data_dir: directory for durable state. ``None`` means pure
            in-memory (nothing survives ``close()``).
        max_message_bytes: reject larger published messages.
        fsync: fsync after every log append (safest, slower).
    """

    def __init__(self, data_dir=None,
                 max_message_bytes=DEFAULT_MAX_MESSAGE_BYTES,
                 fsync=True):
        if max_message_bytes < 1:
            raise MqError("max_message_bytes must be >= 1")
        self.data_dir = data_dir
        self.max_message_bytes = max_message_bytes
        self._fsync = fsync
        self._lock = threading.RLock()
        self._topics = {}
        self._groups = {}     # (topic, group) -> ConsumerGroup
        self._consumers = {}  # consumer_id -> Consumer
        self._closed = False
        if data_dir:
            os.makedirs(data_dir, exist_ok=True)
            self._recover()

    # -- recovery ---------------------------------------------------------

    def _recover(self):
        topics_dir = os.path.join(self.data_dir, "topics")
        if not os.path.isdir(topics_dir):
            return
        for name in sorted(os.listdir(topics_dir)):
            topic_dir = os.path.join(topics_dir, name)
            if not os.path.isdir(topic_dir):
                continue
            topic = Topic.recover(topic_dir, fsync=self._fsync)
            self._topics[topic.name] = topic

    # -- topic management ---------------------------------------------------

    def create_topic(self, name, max_messages=None, max_bytes=None):
        """Create a topic with optional retention limits."""
        _validate_name("topic", name)
        with self._lock:
            self._ensure_open()
            if name in self._topics:
                raise MqError("topic %r already exists" % name)
            log_path = meta_path = None
            if self.data_dir:
                topic_dir = os.path.join(self.data_dir, "topics", name)
                log_path = os.path.join(topic_dir, "messages.log")
                meta_path = os.path.join(topic_dir, "meta.json")
            topic = Topic(name, log_path=log_path, meta_path=meta_path,
                          max_messages=max_messages, max_bytes=max_bytes,
                          fsync=self._fsync)
            topic.save_meta()
            self._topics[name] = topic
            return topic

    def list_topics(self):
        """Return a list of topic info dicts."""
        with self._lock:
            return [{
                "name": t.name,
                "base_offset": t.base_offset,
                "next_offset": t.next_offset,
                "messages": t.size,
                "max_messages": t.max_messages,
                "max_bytes": t.max_bytes,
            } for t in sorted(self._topics.values(),
                              key=lambda t: t.name)]

    def _get_topic(self, name):
        topic = self._topics.get(name)
        if topic is None:
            raise MqError("topic %r does not exist" % name)
        return topic

    # -- publishing -----------------------------------------------------------

    def publish(self, topic_name, message):
        """Append ``message`` to ``topic_name``; returns its offset."""
        with self._lock:
            self._ensure_open()
            topic = self._get_topic(topic_name)
            if isinstance(message, bytes):
                try:
                    message = message.decode("utf-8")
                except UnicodeDecodeError:
                    raise MqError("message bytes must be valid UTF-8")
            if not isinstance(message, str):
                raise MqError(
                    "message must be str or bytes, got %s"
                    % type(message).__name__)
            size = len(message.encode("utf-8"))
            if size > self.max_message_bytes:
                raise MqError(
                    "message of %d bytes exceeds the limit of %d bytes"
                    % (size, self.max_message_bytes))
            return topic.append(message)

    # -- subscribing ------------------------------------------------------------

    def subscribe(self, topic_name, group_name, consumer_id=None):
        """Subscribe to a topic within a consumer group.

        Returns a :class:`Consumer`. Pass an existing ``consumer_id`` to
        resume a previously created consumer identity.
        """
        _validate_name("group", group_name)
        with self._lock:
            self._ensure_open()
            self._get_topic(topic_name)  # raises if missing
            key = (topic_name, group_name)
            group = self._groups.get(key)
            if group is None:
                store_path = None
                if self.data_dir:
                    store_path = os.path.join(
                        self.data_dir, "groups",
                        "%s__%s.json" % (topic_name, group_name))
                group = ConsumerGroup(topic_name, group_name,
                                      store_path=store_path)
                self._groups[key] = group
            if consumer_id is None:
                consumer_id = "c-" + uuid.uuid4().hex[:12]
            consumer = Consumer(self, consumer_id, topic_name, group)
            self._consumers[consumer_id] = consumer
            return consumer

    # -- consumer-facing operations (called by Consumer) -------------------------

    def _poll(self, consumer, max_messages):
        with self._lock:
            self._ensure_open()
            topic = self._get_topic(consumer.topic_name)
            records = consumer._group.poll(consumer.consumer_id, topic,
                                           max_messages)
            return [Message(topic=consumer.topic_name, offset=o, body=b)
                    for o, b in records]

    def _ack(self, consumer, offset):
        with self._lock:
            self._ensure_open()
            self._get_topic(consumer.topic_name)
            consumer._group.ack(consumer.consumer_id, offset)

    def _release(self, consumer):
        with self._lock:
            consumer._group.release(consumer.consumer_id)
            self._consumers.pop(consumer.consumer_id, None)

    # -- lifecycle -----------------------------------------------------------------

    def _ensure_open(self):
        if self._closed:
            raise MqError("broker is closed")

    def close(self):
        with self._lock:
            if self._closed:
                return
            for consumer in list(self._consumers.values()):
                consumer.close()
            for topic in self._topics.values():
                topic.close()
            self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


class Consumer(object):
    """A polling consumer belonging to one consumer group."""

    def __init__(self, broker, consumer_id, topic_name, group):
        self._broker = broker
        self.consumer_id = consumer_id
        self.topic_name = topic_name
        self.group_name = group.group_name
        self._group = group
        self._closed = False

    def poll(self, max_messages=1):
        # type: (int) -> List[Message]
        """Fetch up to ``max_messages`` messages.

        Unacknowledged messages previously delivered to this consumer are
        redelivered first.
        """
        self._ensure_open()
        return self._broker._poll(self, max_messages)

    def ack(self, offset):
        """Acknowledge a previously delivered offset."""
        self._ensure_open()
        self._broker._ack(self, offset)

    def close(self):
        """Close the consumer; its unacked messages become available to
        the rest of the group again."""
        if not self._closed:
            self._closed = True
            self._broker._release(self)

    def _ensure_open(self):
        if self._closed:
            raise MqError("consumer %r is closed" % self.consumer_id)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False
