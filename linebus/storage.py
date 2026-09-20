"""In-memory, append-only event storage."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Deque, Dict, Iterable, List, Tuple


@dataclass(frozen=True, order=True)
class Event:
    sequence: int
    topic: str
    payload: bytes


class EventStore:
    """Retained event log organized by topic.

    The broker owns the only instance and performs all calls while holding its
    lock.  Keeping storage lock-free keeps the ordering rules easy to audit.
    """

    def __init__(self, retention: int = 1000) -> None:
        if retention < 0:
            raise ValueError("retention must be >= 0")
        self.retention = retention
        self._events: Dict[str, Deque[Event]] = defaultdict(deque)

    def add(self, event: Event) -> None:
        if self.retention == 0:
            # A zero retention means no topic retains history without an active
            # eligible subscription. Live subscriber queues are handled by the
            # broker before this method is called.
            return
        queue = self._events[event.topic]
        queue.append(event)
        while len(queue) > self.retention:
            queue.popleft()

    def replay(self, topic: str) -> Tuple[Event, ...]:
        return tuple(self._events.get(topic, ()))

    def get(self, topic: str, sequence: int) -> Event:
        for event in self._events.get(topic, ()):
            if event.sequence == sequence:
                return event
        raise KeyError((topic, sequence))

    def topics(self) -> Tuple[str, ...]:
        return tuple(sorted(name for name, values in self._events.items() if values))

    def clear(self) -> None:
        self._events.clear()

    def restore(self, events: Iterable[Event]) -> None:
        self._events.clear()
        for event in events:
            self.add(event)

    def __len__(self) -> int:
        return sum(len(values) for values in self._events.values())
