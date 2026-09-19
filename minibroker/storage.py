"""In-memory message storage: the retained (undelivered) history.

Every published message is appended to a bounded per-topic FIFO log. The log is
used for two purposes:

* retain messages that had no subscriber at publish time (and, under the
  wildcard/global rules, any message), so late subscribers can replay history;
* guarantee FIFO ordering within a topic.

When the bound ``retain`` is exceeded, oldest messages are evicted (default
policy). The store itself performs no locking; the broker holds the global
state lock while touching it.
"""

from __future__ import annotations

from collections import deque
from typing import Deque, Dict, List, NamedTuple, Optional


class Message(NamedTuple):
    seq: int
    topic: str
    payload: bytes


class MessageStore:
    def __init__(self, retain: int = 1000) -> None:
        if retain < 0:
            raise ValueError("retain must be >= 0")
        self.retain = retain
        self._logs: Dict[str, Deque[Message]] = {}

    def append(self, message: Message) -> Optional[Message]:
        """Append a message; return the evicted message if one was dropped."""
        if self.retain == 0:
            self._logs.pop(message.topic, None)
            return None
        log = self._logs.get(message.topic)
        if log is None:
            log = deque(maxlen=self.retain)
            self._logs[message.topic] = log
        evicted = log[0] if len(log) == self.retain else None
        log.append(message)
        return evicted

    def replay(self, subscription: str) -> List[Message]:
        """Snapshot of retained messages matching a (wildcard) subscription.

        Ordering follows topic alphabetical then sequence; for an exact topic
        this is simply FIFO order.
        """
        out: List[Message] = []
        if subscription == "*":
            for topic in sorted(self._logs):
                out.extend(self._logs[topic])
        elif subscription.endswith("/*"):
            prefix = subscription[:-2]
            if prefix in self._logs:
                out.extend(self._logs[prefix])
            for topic in sorted(self._logs):
                if topic.startswith(prefix + "/"):
                    out.extend(self._logs[topic])
        else:
            log = self._logs.get(subscription)
            if log is not None:
                out.extend(log)
        out.sort(key=lambda msg: msg.seq)
        return out

    def clear(self) -> None:
        self._logs.clear()

    def total_messages(self) -> int:
        return sum(len(log) for log in self._logs.values())

    def topic_count(self) -> int:
        return len(self._logs)
