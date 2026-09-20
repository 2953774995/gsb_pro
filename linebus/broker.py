"""Thread-safe topic logs, subscription table, and subscriber outboxes."""

from __future__ import annotations

from collections import deque
import threading
from typing import Deque, Optional

from .aof import AppendOnlyLog
from .storage import Event, topic_matches, validate_topic


DEFAULT_RETENTION = 1000
DEFAULT_QUEUE_CAPACITY = 1000
FULL_REJECT = "reject"
FULL_BLOCK = "block"
FULL_STRATEGIES = (FULL_REJECT, FULL_BLOCK)


class BrokerError(Exception):
    """Base class for broker-level errors."""


class InvalidTopic(BrokerError):
    pass


class QueueFull(BrokerError):
    pass


class OutboxClosed(BrokerError):
    pass


class SubscriberOutbox:
    """Connection-owned FIFO used by one subscriber connection.

    Events are globally sequenced. Retained-event placeholders reserve slots
    before a subscription pattern becomes visible, preventing newer live events
    from overtaking older retained events. Control replies are sent after all
    already queued events, which gives every subscribe request a clear boundary.
    """

    def __init__(self, connection_id: int, capacity: int, condition: threading.Condition):
        self.connection_id = connection_id
        self.capacity = capacity
        self._condition = condition
        self.events: Deque[Optional[Event]] = deque()
        self._sequences: set[int] = set()
        self.control: Deque[bytes] = deque()
        self.patterns: set[str] = set()
        self.active = True
        self.closed = False

    def event_count(self) -> int:
        return len(self.events)

    def has_sequence(self, sequence: int) -> bool:
        return sequence in self._sequences

    def can_accept(self) -> bool:
        return len(self.events) < self.capacity

    def put_event(self, event: Event, block: bool) -> bool:
        """Deliver a live event. Return False if this outbox no longer matches."""

        with self._condition:
            return self._put_event_locked(event, block)

    def _put_event_locked(self, event: Event, block: bool) -> bool:
        if not self.active or self.closed:
            raise OutboxClosed("subscriber connection is closing")
        if event.sequence in self._sequences:
            return True
        while self._matches(event.topic) and len(self.events) >= self.capacity:
            if not block:
                break
            if not self.active or self.closed:
                raise OutboxClosed("subscriber connection is closing")
            self._condition.wait()
        if not self.active or self.closed:
            raise OutboxClosed("subscriber connection is closing")
        if not self._matches(event.topic):
            return False
        if event.sequence in self._sequences:
            return True
        if len(self.events) >= self.capacity:
            raise QueueFull(f"subscriber queue for connection {self.connection_id} is full")
        self.events.append(event)
        self._sequences.add(event.sequence)
        self._condition.notify_all()
        return True

    def add_subscription(self, pattern: str, retained: list[Event], block: bool) -> None:
        with self._condition:
            self._add_subscription_locked(pattern, retained, block)

    def _add_subscription_locked(self, pattern: str, retained: list[Event], block: bool) -> None:
        if pattern in self.patterns:
            return
        missing = [
            event
            for event in retained
            if event.sequence not in self._sequences and topic_matches(pattern, event.topic)
        ]
        while len(self.events) + len(missing) > self.capacity:
            if not block:
                raise QueueFull("not enough subscriber queue capacity for retained events")
            if not self.active or self.closed:
                raise OutboxClosed("subscriber connection is closing")
            self._condition.wait()
        for _ in missing:
            self.events.append(None)
            # Reserve sequence identity as well as FIFO position.
        # Expose pattern only after all slots are reserved. The broker lock and
        # this condition are the same lock, so no publisher can observe the
        # intermediate state.
        self.patterns.add(pattern)
        index = len(self.events) - len(missing)
        for offset, event in enumerate(missing):
            if event.sequence not in self._sequences:
                self._sequences.add(event.sequence)
            self.events[index + offset] = event
        self._condition.notify_all()

    def clear_events(self) -> None:
        with self._condition:
            self.events.clear()
            self._sequences.clear()
            self._condition.notify_all()

    def remove_pattern(self, pattern: str) -> None:
        with self._condition:
            self.patterns.discard(pattern)
            self._condition.notify_all()

    def put_control(self, frame: bytes) -> None:
        with self._condition:
            if self.closed:
                raise OutboxClosed("subscriber connection is closing")
            self.control.append(frame)
            self._condition.notify_all()

    def get(self, timeout: Optional[float] = None) -> Optional[bytes]:
        with self._condition:
            if not self.events and not self.control and not self.closed:
                self._condition.wait(timeout)
            if self.events:
                event = self.events.popleft()
                if event is None:
                    raise BrokerError("internal error: unfilled subscriber slot")
                self._sequences.discard(event.sequence)
                self._condition.notify_all()
                from .protocol import encode_event

                return encode_event(event.sequence, event.topic, event.payload)
            if self.control:
                return self.control.popleft()
            return None

    def _matches(self, topic: str) -> bool:
        return any(topic_matches(pattern, topic) for pattern in self.patterns)

    def close(self, *, notify: bool = False, clear: bool = False) -> None:
        with self._condition:
            self.active = False
            self.closed = True
            self.patterns.clear()
            if clear:
                self.events.clear()
                self._sequences.clear()
            if notify:
                from .protocol import encode_bye

                self.control.append(encode_bye())
            self._condition.notify_all()

class Broker:
    def __init__(
        self,
        aof: Optional[AppendOnlyLog] = None,
        *,
        retention: int = DEFAULT_RETENTION,
        queue_capacity: int = DEFAULT_QUEUE_CAPACITY,
        full_strategy: str = FULL_REJECT,
    ):
        if retention < 0:
            raise ValueError("retention must be >= 0")
        if queue_capacity < 1:
            raise ValueError("queue_capacity must be >= 1")
        if full_strategy not in FULL_STRATEGIES:
            raise ValueError(f"full_strategy must be one of {FULL_STRATEGIES}")
        self.aof = aof
        self.retention = retention
        self.queue_capacity = queue_capacity
        self.full_strategy = full_strategy
        self.block_on_full = full_strategy == FULL_BLOCK
        self.lock = threading.RLock()
        self.condition = threading.Condition(self.lock)
        self._logs: dict[str, Deque[Event]] = {}
        self._outboxes: dict[int, SubscriberOutbox] = {}
        self._next_connection_id = 1
        self._next_sequence = 1
        self._total_published = 0
        self._total_rejected = 0

    def restore(self) -> None:
        if self.aof is None:
            return
        events, next_sequence = AppendOnlyLog.load(self.aof.path)
        with self.lock:
            for event in events:
                self._append_retained(event)
            self._next_sequence = next_sequence
            self._total_published = len(events)

    def create_outbox(self) -> SubscriberOutbox:
        with self.lock:
            connection_id = self._next_connection_id
            self._next_connection_id += 1
            outbox = SubscriberOutbox(connection_id, self.queue_capacity, self.condition)
            self._outboxes[connection_id] = outbox
            return outbox

    def remove_connection(self, outbox: SubscriberOutbox) -> None:
        with self.lock:
            self._outboxes.pop(outbox.connection_id, None)
            outbox.close(clear=True)

    def validate_publish_topic(self, topic: object) -> str:
        try:
            return validate_topic(topic, allow_wildcard=False)
        except ValueError as exc:
            raise InvalidTopic(str(exc)) from exc

    def validate_subscription_topic(self, topic: object) -> str:
        try:
            return validate_topic(topic, allow_wildcard=True)
        except ValueError as exc:
            raise InvalidTopic(str(exc)) from exc

    def subscribe(self, outbox: SubscriberOutbox, pattern: str) -> None:
        pattern = self.validate_subscription_topic(pattern)
        with self.lock:
            retained = self._retained_for(pattern)
            outbox.add_subscription(pattern, retained, self.block_on_full)

    def unsubscribe(self, outbox: SubscriberOutbox, pattern: str) -> None:
        pattern = self.validate_subscription_topic(pattern)
        with self.lock:
            outbox.remove_pattern(pattern)

    def publish(self, topic: str, payload: bytes) -> Event:
        topic = self.validate_publish_topic(topic)
        if not isinstance(payload, (bytes, bytearray, memoryview)):
            raise TypeError("payload must be bytes")
        payload = bytes(payload)
        with self.lock:
            recipients = [
                outbox
                for outbox in self._outboxes.values()
                if any(topic_matches(pattern, topic) for pattern in outbox.patterns)
            ]
            if not self.block_on_full:
                for outbox in recipients:
                    if not outbox.can_accept():
                        self._total_rejected += 1
                        raise QueueFull(
                            f"subscriber queue for connection {outbox.connection_id} is full"
                        )
            event = Event(self._next_sequence, topic, payload)
            if self.aof is not None:
                self.aof.append(event)
            # Advance only after durable append succeeds, avoiding sequence gaps.
            self._next_sequence += 1
            self._total_published += 1
            self._append_retained(event)
            for outbox in recipients:
                try:
                    outbox.put_event(event, self.block_on_full)
                except OutboxClosed:
                    continue
            return event

    def _retained_for(self, pattern: str) -> list[Event]:
        if pattern.endswith("/*"):
            prefix = pattern[:-1]
            retained: list[Event] = []
            for topic, log in self._logs.items():
                suffix = topic[len(prefix) :] if topic.startswith(prefix) else None
                if suffix is not None and suffix and "/" not in suffix:
                    retained.extend(log)
            retained.sort(key=lambda event: event.sequence)
            return retained
        return list(self._logs.get(pattern, ()))

    def _append_retained(self, event: Event) -> None:
        if self.retention <= 0:
            return
        log = self._logs.get(event.topic)
        if log is None:
            log = deque(maxlen=self.retention)
            self._logs[event.topic] = log
        log.append(event)

    def flush(self) -> None:
        with self.lock:
            self._logs.clear()
            for outbox in self._outboxes.values():
                outbox.clear_events()
            self._next_sequence = 1
            self._total_published = 0
            self._total_rejected = 0
            if self.aof is not None:
                self.aof.truncate()

    def stats(self) -> dict:
        with self.lock:
            return {
                "connections": len(self._outboxes),
                "topics": len(self._logs),
                "retained_events": sum(len(log) for log in self._logs.values()),
                "subscriptions": sum(len(outbox.patterns) for outbox in self._outboxes.values()),
                "queued_events": sum(outbox.event_count() for outbox in self._outboxes.values()),
                "last_sequence": self._next_sequence - 1,
                "total_published": self._total_published,
                "total_rejected": self._total_rejected,
                "retention": self.retention,
                "queue_capacity": self.queue_capacity,
                "full_strategy": self.full_strategy,
            }
