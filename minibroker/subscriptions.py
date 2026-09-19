"""Subscription registry.

Maps subscription patterns (exact topics or ``prefix/*`` / ``*`` wildcards) to
the set of connections subscribed to them. The registry itself is lock free:
the broker serialises all access through its state lock.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Set, TYPE_CHECKING

from .protocol import validate_subscription_topic, validate_topic, topic_matches

if TYPE_CHECKING:  # pragma: no cover
    from .server import ClientConnection


class SubscriptionTable:
    def __init__(self) -> None:
        # pattern -> set of connections
        self._patterns: Dict[str, Set["ClientConnection"]] = {}

    def subscribe(self, conn: "ClientConnection", pattern: str) -> bool:
        validate_subscription_topic(pattern)
        conns = self._patterns.get(pattern)
        if conns is None:
            conns = set()
            self._patterns[pattern] = conns
        if conn in conns:
            return False
        conns.add(conn)
        conn.subscriptions.add(pattern)
        return True

    def unsubscribe(self, conn: "ClientConnection", pattern: str) -> bool:
        validate_subscription_topic(pattern)
        conns = self._patterns.get(pattern)
        if not conns or conn not in conns:
            return False
        conns.discard(conn)
        if not conns:
            del self._patterns[pattern]
        conn.subscriptions.discard(pattern)
        return True

    def remove_connection(self, conn: "ClientConnection") -> None:
        for pattern in list(conn.subscriptions):
            conns = self._patterns.get(pattern)
            if conns is not None:
                conns.discard(conn)
                if not conns:
                    del self._patterns[pattern]
        conn.subscriptions.clear()

    def subscribers_of(self, topic: str) -> List["ClientConnection"]:
        """All connections whose patterns match ``topic``, de-duplicated."""
        seen: Set[int] = set()
        out: List["ClientConnection"] = []
        for pattern, conns in self._patterns.items():
            if topic_matches(pattern, topic):
                for conn in conns:
                    if id(conn) not in seen:
                        seen.add(id(conn))
                        out.append(conn)
        return out

    def pattern_count(self) -> int:
        return len(self._patterns)

    def subscription_count(self) -> int:
        return sum(len(conns) for conns in self._patterns.values())
