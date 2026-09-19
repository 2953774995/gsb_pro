"""In-memory per-topic message backlog (the "queue" of the broker).

Every topic owns a FIFO deque of ``(seq, payload)`` pairs bounded by the
configured *retention*.  The backlog exists so that messages published
while nobody is subscribed can still be delivered to later subscribers
("retained messages").  With ``retention == 0`` nothing is kept and
messages published without a matching subscriber are discarded.
"""

from __future__ import annotations

from collections import deque

from .protocol import pattern_matches


class MessageStore:
    """Thread-safety is provided by the caller (the Broker lock)."""

    def __init__(self, retention: int = 1000):
        if retention < 0:
            raise ValueError("retention must be >= 0")
        self._retention = retention
        self._topics = {}  # topic -> deque[(seq, payload)]

    @property
    def retention(self) -> int:
        return self._retention

    def append(self, topic: str, seq: int, payload: bytes) -> None:
        if self._retention == 0:
            return
        dq = self._topics.setdefault(topic, deque())
        dq.append((seq, payload))
        while len(dq) > self._retention:
            dq.popleft()

    def backlog(self, topic: str):
        """Return the retained ``(seq, payload)`` pairs of one topic."""
        return list(self._topics.get(topic, ()))

    def matching(self, pattern: str):
        """Return retained ``(seq, topic, payload)`` triples matching *pattern*,
        ordered by sequence number."""
        out = []
        for topic, dq in self._topics.items():
            if pattern_matches(pattern, topic):
                out.extend((seq, topic, payload) for seq, payload in dq)
        out.sort(key=lambda item: item[0])
        return out

    def clear(self) -> None:
        self._topics.clear()

    def topic_sizes(self):
        return {topic: len(dq) for topic, dq in self._topics.items()}

    def __len__(self) -> int:
        return sum(len(dq) for dq in self._topics.values())
