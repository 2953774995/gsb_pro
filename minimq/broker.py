"""Broker: owns topics, consumer groups and all on-disk state.

A single re-entrant lock guards every piece of mutable state. All public
operations take the lock, which makes concurrent producers and consumers
safe and makes the poll/ack handshake atomic with respect to retention.
"""

import json
import os
import re
import threading
from urllib.parse import unquote

from .consumer import Consumer, ConsumerGroup, _sanitize
from .errors import MqError, TopicExistsError, TopicNotFoundError
from .retention import RetentionPolicy
from .topic import DEFAULT_MAX_MESSAGE_SIZE, Topic

_VALID_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]*$")


class Broker:
    def __init__(
        self,
        data_dir="minimq-data",
        fsync=True,
        default_max_message_size=DEFAULT_MAX_MESSAGE_SIZE,
    ):
        self.data_dir = os.path.abspath(data_dir)
        self.logs_dir = os.path.join(self.data_dir, "logs")
        self.groups_dir = os.path.join(self.data_dir, "groups")
        os.makedirs(self.logs_dir, exist_ok=True)
        os.makedirs(self.groups_dir, exist_ok=True)

        self.fsync = fsync
        self.default_max_message_size = default_max_message_size
        self.lock = threading.RLock()

        self._topics = {}          # name -> Topic
        self._groups = {}          # (topic, group) -> ConsumerGroup
        self._closed = False

        self._meta_path = os.path.join(self.data_dir, "topics.json")
        self._load()

    # ------------------------------------------------------------------
    # validation & metadata
    # ------------------------------------------------------------------
    @staticmethod
    def _validate_name(kind, name):
        if not isinstance(name, str) or not _VALID_NAME.match(name):
            raise MqError(
                "invalid {} name {!r}: must match {}".format(
                    kind, name, _VALID_NAME.pattern
                )
            )

    def _write_metadata(self):
        data = {
            name: topic.config_dict()
            for name, topic in self._topics.items()
        }
        tmp = "{}.tmp".format(self._meta_path)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self._meta_path)

    def _load(self):
        data = {}
        if os.path.exists(self._meta_path):
            with open(self._meta_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        # Also tolerate a missing metadata file: recover topics from the
        # log files present in the logs directory.
        if not data:
            for fname in os.listdir(self.logs_dir):
                if fname.endswith(".log"):
                    data[fname[:-4]] = {}
        for name, cfg in data.items():
            cfg = cfg or {}
            retention = RetentionPolicy.from_dict(cfg.get("retention"))
            topic = Topic(
                name=name,
                log_path=os.path.join(self.logs_dir, "{}.log".format(_sanitize(name))),
                retention=retention,
                max_message_size=cfg.get(
                    "max_message_size", self.default_max_message_size
                ),
                fsync=self.fsync,
                on_evict=self._after_eviction,
            )
            self._topics[name] = topic

    def _after_eviction(self, topic_name, offsets):
        # Called while the lock is held (from Topic.publish).
        for (t, _g), group in list(self._groups.items()):
            if t == topic_name:
                group.evict_offsets(offsets)

    # ------------------------------------------------------------------
    # topics
    # ------------------------------------------------------------------
    def create_topic(
        self, name, max_messages=None, max_bytes=None, max_message_size=None
    ):
        """Create a topic; it is an error if one with the name exists."""
        self._validate_name("topic", name)
        with self.lock:
            if self._closed:
                raise MqError("broker is closed")
            if name in self._topics:
                raise TopicExistsError("topic {!r} already exists".format(name))
            retention = RetentionPolicy(max_messages, max_bytes)
            topic = Topic(
                name=name,
                log_path=os.path.join(self.logs_dir, "{}.log".format(_sanitize(name))),
                retention=retention,
                max_message_size=max_message_size or self.default_max_message_size,
                fsync=self.fsync,
                on_evict=self._after_eviction,
            )
            self._topics[name] = topic
            self._write_metadata()
            return topic

    def delete_topic(self, name):
        with self.lock:
            topic = self._topic(name)
            topic.close()
            del self._topics[name]
            # Remove groups attached to this topic.
            for key in [k for k in self._groups if k[0] == name]:
                del self._groups[key]
            prefix = "{}!".format(_sanitize(name))
            for fname in list(os.listdir(self.groups_dir)):
                if fname.startswith(prefix) and fname.endswith(".json"):
                    os.remove(os.path.join(self.groups_dir, fname))
            log_path = os.path.join(self.logs_dir, "{}.log".format(_sanitize(name)))
            if os.path.exists(log_path):
                os.remove(log_path)
            self._write_metadata()

    def list_topics(self):
        with self.lock:
            return sorted(self._topics)

    def topic_info(self, name=None):
        """Return topic names with offsets, sizes and retention settings."""
        with self.lock:
            names = [name] if name is not None else sorted(self._topics)
            result = {}
            for n in names:
                t = self._topic(n)
                result[n] = {
                    "earliest_offset": t.earliest_offset(),
                    "latest_offset": t.latest_offset(),
                    "next_offset": t.next_offset(),
                    "message_count": len(t),
                    "size_bytes": t.size_bytes(),
                    "retention": t.retention.to_dict(),
                    "max_message_size": t.max_message_size,
                }
            return result if name is None else result[name]

    def _topic(self, name):
        try:
            return self._topics[name]
        except KeyError:
            raise TopicNotFoundError(
                "topic {!r} does not exist; create it first".format(name)
            )

    # ------------------------------------------------------------------
    # produce / consume
    # ------------------------------------------------------------------
    def publish(self, topic, message):
        """Append ``message`` (str encoded utf-8 or bytes); return offset."""
        if self._closed:
            raise MqError("broker is closed")
        if isinstance(message, str):
            payload = message.encode("utf-8")
        elif isinstance(message, (bytes, bytearray)):
            payload = bytes(message)
        else:
            raise MqError("message must be str or bytes, got {}".format(type(message).__name__))
        with self.lock:
            t = self._topic(topic)
            return t.publish(payload)

    def subscribe(self, topic, group):
        """Subscribe to a topic under a consumer group; returns Consumer.

        Calling subscribe multiple times with the same group creates
        additional consumers that share the group's offsets (load
        balancing). Different group names consume independently.
        """
        self._validate_name("group", group)
        with self.lock:
            if self._closed:
                raise MqError("broker is closed")
            self._topic(topic)  # raises TopicNotFoundError if absent
            key = (topic, group)
            if key not in self._groups:
                grp0 = ConsumerGroup(topic, group, self.groups_dir, self)
                grp0._persist()  # anchor the group durably on first subscribe
                self._groups[key] = grp0
            grp = self._groups[key]
            consumer = Consumer(grp, self)
            return consumer

    # ------------------------------------------------------------------
    # introspection (mostly for CLI / tests)
    # ------------------------------------------------------------------
    def group_progress(self, topic, group):
        """Return ``(hwm, sorted gaps)`` for a group's persisted progress."""
        with self.lock:
            self._topic(topic)
            key = (topic, group)
            if key not in self._groups:
                grp = ConsumerGroup(topic, group, self.groups_dir, self)
            else:
                grp = self._groups[key]
            return grp.hwm, sorted(grp.gaps)

    def list_groups(self, topic=None):
        """List groups known on disk and in memory, optionally per topic."""
        with self.lock:
            found = set()
            for fname in os.listdir(self.groups_dir):
                if fname.endswith(".json"):
                    base = fname[:-5]
                    if "!" in base:
                        t_name, g_name = base.split("!", 1)
                        found.add((unquote(t_name), unquote(g_name)))
            found |= {(t, g) for (t, g) in self._groups}
            if topic is not None:
                found = {p for p in found if p[0] == topic}
            return sorted(found)

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------
    def close(self):
        with self.lock:
            if self._closed:
                return
            self._closed = True
            for topic in self._topics.values():
                topic.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False
