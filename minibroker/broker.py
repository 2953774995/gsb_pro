"""Broker core: topic stores, subscription table, sequencing, policies.

Thread-safe: every public method takes the broker lock, so publishes are
totally ordered and each subscriber queue receives messages in publish
order.  Persistence (AOF) is written inside the same critical section,
before in-memory state changes, so file order matches execution order.
"""

import queue
import threading
from collections import deque

from .aof import AOF
from .protocol import is_valid_pattern, is_valid_topic


class BrokerError(Exception):
    """Base class for broker-level errors (reported as -ERR)."""


class InvalidTopicError(BrokerError):
    pass


class InvalidPatternError(BrokerError):
    pass


class NotSubscribedError(BrokerError):
    pass


class QueueFullError(BrokerError):
    pass


def pattern_matches(pattern, topic):
    """``foo/*`` matches any topic under ``foo/``; otherwise exact match."""
    if pattern.endswith("/*"):
        return topic.startswith(pattern[:-1])
    return pattern == topic


class _Connection:
    __slots__ = ("queue", "patterns")

    def __init__(self, delivery_queue):
        self.queue = delivery_queue
        self.patterns = set()


class Broker:
    def __init__(self, retention=1000, max_queue=10000, full_policy="error",
                 aof_path=None):
        if full_policy not in ("error", "block"):
            raise ValueError("full_policy must be 'error' or 'block'")
        if retention < 0 or max_queue < 1:
            raise ValueError("retention must be >= 0 and max_queue >= 1")
        self.retention = retention
        self.max_queue = max_queue
        self.full_policy = full_policy
        self._lock = threading.RLock()
        self._topics = {}        # topic -> deque[(seq, payload)], bounded
        self._connections = {}   # conn_id -> _Connection
        self._next_seq = 1
        self._published = 0
        self._delivered = 0
        self._aof = None
        if aof_path:
            entries, next_seq = AOF.load(aof_path)
            self._next_seq = next_seq
            for seq, topic, payload in entries:
                self._store(topic, seq, payload)
            self._aof = AOF(aof_path)

    # -- connection / subscription table --------------------------------

    def register_connection(self, conn_id):
        """Attach a delivery queue for a new connection."""
        with self._lock:
            delivery_queue = queue.Queue(maxsize=self.max_queue)
            self._connections[conn_id] = _Connection(delivery_queue)
            return delivery_queue

    def deregister_connection(self, conn_id):
        """Drop all subscriptions; undelivered queued messages are
        discarded for this connection (retained copies stay in the
        topic stores according to the retention policy)."""
        with self._lock:
            self._connections.pop(conn_id, None)

    def subscribe(self, conn_id, pattern):
        if not is_valid_pattern(pattern):
            raise InvalidPatternError("invalid topic pattern: %r" % pattern)
        with self._lock:
            conn = self._connections.get(conn_id)
            if conn is None:
                raise BrokerError("unknown connection")
            conn.patterns.add(pattern)
            # Replay retained history atomically with the subscription so
            # no concurrent publish is missed or duplicated.
            retained = []
            for topic, stored in self._topics.items():
                if pattern_matches(pattern, topic):
                    retained.extend(
                        (seq, topic, payload) for seq, payload in stored
                    )
            retained.sort(key=lambda item: item[0])
            for item in retained:
                self._put(conn_id, conn.queue, item)

    def unsubscribe(self, conn_id, pattern):
        with self._lock:
            conn = self._connections.get(conn_id)
            if conn is None:
                raise BrokerError("unknown connection")
            if pattern not in conn.patterns:
                raise NotSubscribedError("not subscribed to %r" % pattern)
            conn.patterns.discard(pattern)

    # -- publishing ------------------------------------------------------

    def publish(self, topic, payload):
        """Publish payload to topic; returns the global sequence number."""
        if not is_valid_topic(topic):
            raise InvalidTopicError("invalid topic: %r" % topic)
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        payload = bytes(payload)
        with self._lock:
            targets = [
                (conn_id, conn.queue)
                for conn_id, conn in self._connections.items()
                if any(pattern_matches(p, topic) for p in conn.patterns)
            ]
            if self.full_policy == "error":
                for _, target_queue in targets:
                    if target_queue.full():
                        raise QueueFullError(
                            "subscriber queue full (max_queue=%d)"
                            % self.max_queue
                        )
            seq = self._next_seq
            if self._aof is not None:
                self._aof.append_publish(seq, topic, payload)
            self._next_seq += 1
            self._store(topic, seq, payload)
            for conn_id, target_queue in targets:
                self._put(conn_id, target_queue, (seq, topic, payload))
                self._delivered += 1
            self._published += 1
            return seq

    def _store(self, topic, seq, payload):
        stored = self._topics.get(topic)
        if stored is None:
            stored = self._topics[topic] = deque(maxlen=self.retention)
        stored.append((seq, payload))

    def _put(self, conn_id, target_queue, item):
        if self.full_policy == "error":
            target_queue.put_nowait(item)
            return
        # Block policy: wait for room, but give up if the subscriber's
        # connection went away meanwhile.
        while True:
            try:
                target_queue.put(item, timeout=0.1)
                return
            except queue.Full:
                if conn_id not in self._connections:
                    return

    # -- maintenance -----------------------------------------------------

    def flush(self):
        """Clear all retained messages and the AOF.  The global sequence
        number is kept (and persisted) so it stays monotonic."""
        with self._lock:
            self._topics.clear()
            if self._aof is not None:
                self._aof.reset()
                self._aof.append_seq(self._next_seq)

    def stats(self):
        with self._lock:
            return {
                "published": self._published,
                "delivered": self._delivered,
                "stored": sum(len(s) for s in self._topics.values()),
                "topics": len(self._topics),
                "connections": len(self._connections),
                "next_seq": self._next_seq,
            }

    def close(self):
        with self._lock:
            if self._aof is not None:
                self._aof.close()
