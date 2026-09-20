"""Core thread-safe publish/subscribe broker."""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, Iterable, List, Optional, Set, Tuple

from .persistence import AOFWriter, read_aof
from .protocol import topic_matches, validate_topic
from .storage import Event, EventStore


class BrokerError(Exception):
    """A command-level broker failure."""


class BrokerShutdown(Exception):
    """Raised to blocked operations after graceful shutdown starts."""


@dataclass
class SubscriptionTable:
    """Pattern -> subscriber IDs."""

    patterns: Dict[str, Set[int]] = field(default_factory=dict)

    def add(self, subscriber_id: int, pattern: str) -> None:
        self.patterns.setdefault(pattern, set()).add(subscriber_id)

    def remove(self, subscriber_id: int, pattern: str) -> None:
        subscribers = self.patterns.get(pattern)
        if subscribers:
            subscribers.discard(subscriber_id)
            if not subscribers:
                del self.patterns[pattern]

    def remove_subscriber(self, subscriber_id: int) -> None:
        for pattern in list(self.patterns):
            self.remove(subscriber_id, pattern)

    def matches(self, topic: str) -> Set[int]:
        result: Set[int] = set()
        for pattern, subscribers in self.patterns.items():
            if topic_matches(pattern, topic):
                result.update(subscribers)
        return result

    def subscriber_patterns(self, subscriber_id: int) -> Set[str]:
        return {
            pattern
            for pattern, subscribers in self.patterns.items()
            if subscriber_id in subscribers
        }


@dataclass
class Subscriber:
    identifier: int
    # One FIFO queue per initialized topic. Terminal wildcards may initialize
    # several topics; the consumer receives the oldest event across them.
    queues: Dict[str, Deque[Event]] = field(default_factory=dict)
    patterns: Set[str] = field(default_factory=set)

    def pending_count(self) -> int:
        return sum(len(queue) for queue in self.queues.values())

    def has_next(self) -> bool:
        return any(queue for queue in self.queues.values())

    def pop_oldest(self) -> Optional[Event]:
        candidate: Optional[Event] = None
        candidate_topic: Optional[str] = None
        for topic, queue in self.queues.items():
            if queue and (candidate is None or queue[0].sequence < candidate.sequence):
                candidate = queue[0]
                candidate_topic = topic
        if candidate is None or candidate_topic is None:
            return None
        return self.queues[candidate_topic].popleft()


class Broker:
    """Thread-safe queue manager, subscription registry and AOF coordinator."""

    def __init__(
        self,
        *,
        retention: int = 1000,
        queue_capacity: int = 1000,
        queue_full_policy: str = "block",
        aof_path: str = ".linebus.aof",
        fsync: bool = False,
    ) -> None:
        if retention < 0:
            raise ValueError("retention must be >= 0")
        if queue_capacity < 0:
            raise ValueError("queue_capacity must be >= 0 (0 means unbounded)")
        if queue_full_policy not in {"block", "error"}:
            raise ValueError("queue_full_policy must be 'block' or 'error'")
        self.retention = retention
        self.queue_capacity = queue_capacity
        self.queue_full_policy = queue_full_policy
        self.aof_path = aof_path
        self._condition = threading.Condition()
        self._store = EventStore(retention)
        self._table = SubscriptionTable()
        self._subscribers: Dict[int, Subscriber] = {}
        self._next_subscriber_id = 1
        self._next_sequence = 1
        self._published_count = 0
        self._delivered_count = 0
        self._shutting_down = False
        self._aof: Optional[AOFWriter] = None
        if aof_path:
            self._aof = AOFWriter(aof_path, fsync=fsync)
            self._aof.open_for_append()
            events, next_sequence = read_aof(aof_path)
            self._store.restore(events)
            self._next_sequence = next_sequence
            self._published_count = next_sequence - 1

    def close(self) -> None:
        with self._condition:
            self._shutting_down = True
            self._condition.notify_all()
        if self._aof is not None:
            self._aof.close()
            self._aof = None

    def add_subscriber(self) -> int:
        with self._condition:
            self._check_running()
            identifier = self._next_subscriber_id
            self._next_subscriber_id += 1
            self._subscribers[identifier] = Subscriber(identifier)
            return identifier

    def remove_subscriber(self, subscriber_id: int) -> None:
        with self._condition:
            self._subscribers.pop(subscriber_id, None)
            self._table.remove_subscriber(subscriber_id)
            # Removing a blocked slow consumer can unblock publishers.
            self._condition.notify_all()

    def _get_subscriber(self, subscriber_id: int) -> Subscriber:
        try:
            return self._subscribers[subscriber_id]
        except KeyError as exc:
            raise BrokerError("subscriber connection is not registered") from exc

    def _check_running(self) -> None:
        if self._shutting_down:
            raise BrokerShutdown("broker is shutting down")

    def _ensure_topic_queue(
        self, subscriber: Subscriber, topic: str, *, replay: bool
    ) -> None:
        if topic in subscriber.queues:
            return
        queue: Deque[Event] = deque()
        if replay:
            for event in self._store.replay(topic):
                queue.append(event)
            if self.queue_capacity:
                while len(queue) > self.queue_capacity:
                    queue.popleft()
        subscriber.queues[topic] = queue

    def subscribe(self, subscriber_id: int, pattern: str) -> None:
        pattern = validate_topic(pattern, allow_wildcard=True)
        with self._condition:
            self._check_running()
            subscriber = self._get_subscriber(subscriber_id)
            if pattern not in subscriber.patterns:
                subscriber.patterns.add(pattern)
                self._table.add(subscriber_id, pattern)
                if pattern.endswith("/*"):
                    # Activate every retained topic in the wildcard namespace.
                    for topic in self._store.topics():
                        if topic_matches(pattern, topic):
                            self._ensure_topic_queue(subscriber, topic, replay=True)
                else:
                    self._ensure_topic_queue(subscriber, pattern, replay=True)
            self._condition.notify_all()

    def unsubscribe(self, subscriber_id: int, pattern: str) -> None:
        pattern = validate_topic(pattern, allow_wildcard=True)
        with self._condition:
            self._check_running()
            subscriber = self._get_subscriber(subscriber_id)
            if pattern in subscriber.patterns:
                subscriber.patterns.remove(pattern)
                self._table.remove(subscriber_id, pattern)
                for topic in list(subscriber.queues):
                    if not any(topic_matches(other, topic) for other in subscriber.patterns):
                        # The connection explicitly canceled this namespace.
                        # Remaining backlog is therefore not delivered to it.
                        del subscriber.queues[topic]
            self._condition.notify_all()

    def _matching_subscribers(self, topic: str) -> Tuple[Subscriber, ...]:
        return tuple(
            self._subscribers[identifier]
            for identifier in self._table.matches(topic)
            if identifier in self._subscribers
        )

    def _capacity_ready(self, subscribers: Iterable[Subscriber], topic: str) -> bool:
        if not self.queue_capacity:
            return True
        return all(
            len(subscriber.queues.get(topic, ())) < self.queue_capacity
            for subscriber in subscribers
        )

    def publish(self, topic: str, payload: bytes, *, timeout: Optional[float] = None) -> Event:
        topic = validate_topic(topic, allow_wildcard=False)
        if not isinstance(payload, (bytes, bytearray)):
            raise TypeError("payload must be bytes")
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._condition:
            self._check_running()
            subscribers = self._matching_subscribers(topic)

            if self.queue_capacity and subscribers:
                if self.queue_full_policy == "error" and not self._capacity_ready(subscribers, topic):
                    raise BrokerError(
                        f"queue for topic {topic!r} is full; policy=error"
                    )
                while not self._capacity_ready(subscribers, topic):
                    remaining = None
                    if deadline is not None:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise BrokerError("timed out waiting for queue capacity")
                    self._condition.wait(timeout=remaining)
                    self._check_running()
                    # Subscriptions can change while blocked for backpressure.
                    subscribers = self._matching_subscribers(topic)

            event = Event(self._next_sequence, topic, bytes(payload))
            self._next_sequence += 1
            self._published_count += 1
            if self._aof is not None:
                try:
                    self._aof.append_event(event)
                except OSError as exc:
                    # No other publisher can run while this lock is held, so
                    # rolling back the reserved sequence is unambiguous.
                    self._next_sequence -= 1
                    self._published_count -= 1
                    raise BrokerError(f"AOF write failed: {exc}") from exc

            self._store.add(event)
            for subscriber in subscribers:
                # A subscriber can match through an exact and wildcard pattern.
                # A single per-topic queue makes that delivery idempotent.
                self._ensure_topic_queue(subscriber, topic, replay=False)
                subscriber.queues[topic].append(event)
            self._condition.notify_all()
            return event

    def next_event(
        self,
        subscriber_id: int,
        *,
        timeout: Optional[float] = None,
    ) -> Optional[Event]:
        with self._condition:
            subscriber = self._get_subscriber(subscriber_id)
            if not subscriber.has_next():
                if self._shutting_down:
                    raise BrokerShutdown("broker is shutting down")
                if timeout == 0:
                    return None
                self._condition.wait(timeout=timeout)
                if self._shutting_down:
                    raise BrokerShutdown("broker is shutting down")
            event = subscriber.pop_oldest()
            if event is not None:
                self._delivered_count += 1
                self._condition.notify_all()
            return event

    def flush(self) -> None:
        with self._condition:
            self._check_running()
            self._store.clear()
            for subscriber in self._subscribers.values():
                subscriber.queues.clear()
            self._next_sequence = 1
            self._published_count = 0
            self._delivered_count = 0
            if self._aof is not None:
                self._aof.reset(1)
            self._condition.notify_all()

    def begin_shutdown(self) -> None:
        with self._condition:
            self._shutting_down = True
            self._condition.notify_all()

    def stats(self) -> Dict[str, int]:
        with self._condition:
            return {
                "next_sequence": self._next_sequence,
                "published_events": self._published_count,
                "delivered_events": self._delivered_count,
                "retained_events": len(self._store),
                "subscribers": len(self._subscribers),
                "subscriptions": sum(
                    len(subscriber.patterns) for subscriber in self._subscribers.values()
                ),
                "queued_events": sum(
                    subscriber.pending_count() for subscriber in self._subscribers.values()
                ),
                "retention": self.retention,
                "queue_capacity": self.queue_capacity,
            }
