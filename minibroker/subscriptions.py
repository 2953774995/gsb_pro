"""Subscription registry: which connection is subscribed to which pattern."""

from __future__ import annotations

from .protocol import pattern_matches


class SubscriptionTable:
    """Maps connection ids to ``{pattern: mailbox}`` dictionaries.

    Thread-safety is provided by the caller (the Broker lock).
    """

    def __init__(self):
        self._subs = {}  # conn_id -> {pattern: mailbox}

    def add(self, conn_id, pattern: str, mailbox) -> None:
        self._subs.setdefault(conn_id, {})[pattern] = mailbox

    def remove(self, conn_id, pattern: str) -> bool:
        patterns = self._subs.get(conn_id)
        if not patterns or pattern not in patterns:
            return False
        del patterns[pattern]
        if not patterns:
            del self._subs[conn_id]
        return True

    def remove_all(self, conn_id) -> None:
        self._subs.pop(conn_id, None)

    def matching(self, topic: str):
        """Return the distinct mailboxes subscribed to *topic* (one per
        connection, even if several of its patterns match)."""
        seen = set()
        out = []
        for patterns in self._subs.values():
            for pattern, mailbox in patterns.items():
                if pattern_matches(pattern, topic) and id(mailbox) not in seen:
                    seen.add(id(mailbox))
                    out.append(mailbox)
        return out

    def count(self) -> int:
        return sum(len(p) for p in self._subs.values())

    def patterns_of(self, conn_id):
        return list(self._subs.get(conn_id, ()))
