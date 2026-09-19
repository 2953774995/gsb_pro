"""Broker core: global sequence numbers, fan-out, retention, persistence.

Concurrency model
-----------------
A single :class:`threading.RLock` guards the sequence counter, the message
store, the subscription table and the AOF.  Because every publish mutates
all of them while holding the lock, each subscriber's mailbox receives
messages in exact publish order and the AOF order matches the execution
order.

Backpressure
------------
Each subscriber connection owns a bounded :class:`Mailbox`.  When a
publish would overflow a subscriber's mailbox the configured ``on_full``
policy applies:

* ``"error"`` (default): the whole PUBLISH fails with :class:`QueueFull`
  and nothing is stored or delivered.
* ``"block"``: the publishing thread waits until every matching mailbox
  has room (or the subscriber disconnects, which raises
  :class:`QueueFull`).
"""

from __future__ import annotations

import queue
import threading
import time

from .aof import AofWriter, replay_aof
from .protocol import validate_pattern, validate_topic
from .store import MessageStore
from .subscriptions import SubscriptionTable


class QueueFull(Exception):
    """Raised when a subscriber mailbox is full and the policy is 'error'
    (or a blocked subscriber disconnected while we waited)."""


class Mailbox:
    """Bounded per-connection outbound queue.

    Items are ``(seq, topic, payload)`` message tuples produced by the
    broker; the networking layer may additionally push raw ``bytes``
    (command responses, BYE notifications) into the same queue.
    """

    def __init__(self, maxsize: int = 10000, is_alive=None):
        self.queue = queue.Queue(maxsize=maxsize)
        self._is_alive = is_alive or (lambda: True)

    def full(self) -> bool:
        return self.queue.full()

    def put_message(self, item, block: bool) -> None:
        if not block:
            self.queue.put_nowait(item)
            return
        while True:
            try:
                self.queue.put(item, timeout=0.1)
                return
            except queue.Full:
                if not self._is_alive():
                    raise QueueFull("subscriber disconnected")

    def put_response(self, data: bytes) -> None:
        """Enqueue a raw protocol frame (used by the server layer)."""
        self.queue.put_nowait(data)


class Broker:
    def __init__(
        self,
        retention: int = 1000,
        on_full: str = "error",
        aof_path: str | None = None,
        aof_fsync: bool = False,
    ):
        if on_full not in ("error", "block"):
            raise ValueError("on_full must be 'error' or 'block'")
        self._lock = threading.RLock()
        self._store = MessageStore(retention)
        self._subs = SubscriptionTable()
        self._on_full = on_full
        self._seq = 0
        self._published = 0
        self._started = time.time()
        self._aof = None
        if aof_path is not None:
            records, floor = replay_aof(aof_path)
            self._seq = floor
            for seq, topic, payload in records:
                self._store.append(topic, seq, payload)
                if seq > self._seq:
                    self._seq = seq
                self._published += 1
            self._aof = AofWriter(aof_path, fsync=aof_fsync)

    # -- properties ------------------------------------------------------

    @property
    def last_seq(self) -> int:
        with self._lock:
            return self._seq

    @property
    def on_full_policy(self) -> str:
        return self._on_full

    # -- publishing ------------------------------------------------------

    def publish(self, topic: str, payload: bytes) -> int:
        """Publish *payload* to *topic*; returns the global sequence number."""
        validate_topic(topic)
        if not isinstance(payload, (bytes, bytearray)):
            raise TypeError("payload must be bytes")
        payload = bytes(payload)
        with self._lock:
            targets = self._subs.matching(topic)
            if self._on_full == "error":
                for mb in targets:
                    if mb.full():
                        raise QueueFull(
                            "subscriber queue full for topic %r" % topic
                        )
            seq = self._seq + 1
            if self._aof is not None:
                self._aof.append(seq, topic, payload)  # durable before apply
            self._seq = seq
            self._store.append(topic, seq, payload)
            item = (seq, topic, payload)
            block = self._on_full == "block"
            for mb in targets:
                mb.put_message(item, block=block)
            self._published += 1
            return seq

    # -- subscriptions ---------------------------------------------------

    def subscribe(self, conn_id, pattern: str, mailbox: Mailbox) -> None:
        """Register *pattern* for *conn_id* and replay the retained backlog.

        The replay happens under the broker lock so no live message can
        overtake the backlog in the subscriber's mailbox.
        """
        validate_pattern(pattern)
        with self._lock:
            self._subs.add(conn_id, pattern, mailbox)
            for seq, topic, payload in self._store.matching(pattern):
                try:
                    mailbox.put_message((seq, topic, payload), block=False)
                except queue.Full:
                    # Mailbox already full: drop the rest of the backlog for
                    # this subscriber (documented behaviour).
                    break

    def unsubscribe(self, conn_id, pattern: str) -> bool:
        validate_pattern(pattern)
        with self._lock:
            return self._subs.remove(conn_id, pattern)

    def connection_closed(self, conn_id) -> None:
        with self._lock:
            self._subs.remove_all(conn_id)

    # -- administration --------------------------------------------------

    def flush(self) -> None:
        """Clear all retained messages and reset the AOF (sequence numbers
        keep increasing thanks to the #SEQ checkpoint)."""
        with self._lock:
            self._store.clear()
            if self._aof is not None:
                self._aof.reset(self._seq)

    def stats(self) -> dict:
        with self._lock:
            return {
                "uptime_seconds": round(time.time() - self._started, 3),
                "last_seq": self._seq,
                "published_total": self._published,
                "retention": self._store.retention,
                "on_full": self._on_full,
                "backlog_messages": len(self._store),
                "topics": self._store.topic_sizes(),
                "subscriptions": self._subs.count(),
            }

    def close(self) -> None:
        with self._lock:
            if self._aof is not None:
                self._aof.close()
