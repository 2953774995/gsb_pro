"""Thread-safe in-memory broker state: retention queues, subscriptions and fan-out."""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, List, Optional

from .exceptions import BrokerError, PersistenceError, QueueFullError
from .messages import StoredMessage
from .persistence import AppendOnlyLog
from .topics import (
    InvalidTopicError,
    is_wildcard,
    prefixes_for_literal,
    topic_matches_prefix,
    validate_topic,
    wildcard_prefix,
)


@dataclass
class Subscription:
    id: int
    conn_id: int
    pattern: bytes


class Broker:
    """All mutation of routing/retention state is guarded by one re-entrant lock.

    The global lock keeps the critical section simple and makes the documented
    execution order precise: sequence assignment, AOF append, retention and
    fan-out happen atomically with respect to other commands.  Network writes
    happen after this state update, with each connection owning a bounded queue
    and a dedicated writer thread.
    """

    def __init__(
        self,
        aof: "Optional[AppendOnlyLog | str]" = None,
        *,
        retention: int = 1000,
        max_client_queue: int = 0,
    ):
        if retention < 0:
            raise ValueError("retention must be >= 0")
        if max_client_queue < 0:
            raise ValueError("max_client_queue must be >= 0 (0 means unlimited)")

        self.retention_limit = retention
        self.max_client_queue = max_client_queue
        self._lock = threading.RLock()

        if aof is None or isinstance(aof, str):
            self.aof = AppendOnlyLog(aof or ".broker.aof")
        else:
            self.aof = aof

        try:
            replay = self.aof.replay()
        except Exception:
            self.aof.close()
            raise
        self._next_sequence = replay.next_sequence
        self._published_total = len(replay.messages)
        self._retained: Dict[bytes, Deque[StoredMessage]] = {}
        for message in replay.messages:
            self._remember(message)

        self._exact_subscriptions: Dict[bytes, Dict[int, Subscription]] = {}
        self._wild_subscriptions: Dict[bytes, Dict[int, Subscription]] = {}
        self._connections: Dict[int, "object"] = {}
        self._closed_connection_ids = set()
        self._next_subscription_id = 1
        self._next_connection_id = 1

    # ------------------------------------------------------------------ state
    def close(self) -> None:
        with self._lock:
            if self.aof is None:
                return
            self.aof.close()
            self.aof = None

    def register_connection(self, conn: "object") -> int:
        with self._lock:
            conn_id = self._next_connection_id
            self._next_connection_id += 1
            conn.id = conn_id  # type: ignore[attr-defined]
            self._connections[conn_id] = conn
            self._closed_connection_ids.discard(conn_id)
            return conn_id

    def unregister_connection(self, conn: "object") -> None:
        with self._lock:
            # Remove every routing entry belonging to this connection.
            patterns = list(getattr(conn, "subscriptions", {}).keys())
            for pattern in patterns:
                self._remove_subscription(conn, pattern)  # type: ignore[arg-type]
            conn_id = getattr(conn, "id", -1)
            self._connections.pop(conn_id, None)
            if conn_id >= 0:
                self._closed_connection_ids.add(conn_id)
            conn.clear_pending()  # type: ignore[attr-defined]

    # ---------------------------------------------------------------- publish
    def publish(self, topic: bytes, payload: bytes) -> StoredMessage:
        try:
            validate_topic(topic, allow_wildcard=False)
        except InvalidTopicError as exc:
            raise BrokerError(str(exc)) from exc

        with self._lock:
            subscriptions = self._matching_subscriptions(topic)

            # Reject before assigning a sequence or writing AOF.  The default
            # limit is zero (unlimited); a positive limit gives back-pressure
            # rather than silently dropping a message.
            if self.max_client_queue:
                seen = set()
                for sub in subscriptions:
                    conn = None if sub.conn_id in self._closed_connection_ids else self._connections.get(sub.conn_id)
                    if conn is None or id(conn) in seen:
                        continue
                    seen.add(id(conn))
                    if conn.pending_count() >= self.max_client_queue:  # type: ignore[attr-defined]
                        raise QueueFullError(
                            f"client queue full (limit={self.max_client_queue})"
                        )

            sequence = self._next_sequence
            message = StoredMessage(sequence, topic, payload)
            try:
                self.aof.append(message)
            except PersistenceError:
                # No broker state has changed yet.  The sequence counter has
                # not advanced, so future successful publishes remain dense.
                raise

            self._next_sequence = sequence + 1
            self._published_total += 1
            self._remember(message)

            # One connection may have overlapping patterns (for example
            # "a/*" and "a/b/*").  Deliver one PUB while tagging it with every
            # still-active matching subscription.
            by_conn: Dict[int, List[Subscription]] = {}
            for sub in subscriptions:
                by_conn.setdefault(sub.conn_id, []).append(sub)
            for conn_id, matched in by_conn.items():
                conn = None if conn_id in self._closed_connection_ids else self._connections.get(conn_id)
                if conn is not None:
                    conn.enqueue_message(  # type: ignore[attr-defined]
                        tuple(item.id for item in matched), message
                    )
            return message

    def _remember(self, message: StoredMessage) -> None:
        if self.retention_limit == 0:
            return
        queue = self._retained.get(message.topic)
        if queue is None:
            queue = deque(maxlen=self.retention_limit)
            self._retained[message.topic] = queue
        queue.append(message)

    def _matching_subscriptions(self, topic: bytes) -> List[Subscription]:
        found: List[Subscription] = []
        exact = self._exact_subscriptions.get(topic)
        if exact:
            found.extend(exact.values())

        for prefix in prefixes_for_literal(topic):
            if not topic_matches_prefix(topic, prefix):
                continue
            wild = self._wild_subscriptions.get(prefix)
            if wild:
                found.extend(wild.values())
        global_wild = self._wild_subscriptions.get(b"")
        if global_wild:
            found.extend(global_wild.values())
        return found

    # -------------------------------------------------------------- subscribe
    def subscribe(self, conn: "object", pattern: bytes) -> int:
        try:
            validate_topic(pattern, allow_wildcard=True)
        except InvalidTopicError as exc:
            raise BrokerError(str(exc)) from exc

        with self._lock:
            existing = conn.subscriptions.get(pattern)  # type: ignore[attr-defined]
            if existing is not None:
                return existing.id

            # Backfill must respect the same bounded queue policy as live
            # delivery and never duplicate a message already delivered on this
            # same connection through another overlapping subscription.
            backlog = self._retained_for(pattern)
            backlog.sort(key=lambda item: item.sequence)
            new_backlog = [
                message
                for message in backlog
                if not conn.has_seen_sequence(message.sequence)  # type: ignore[attr-defined]
            ]
            if self.max_client_queue and (
                conn.pending_count() + len(new_backlog) > self.max_client_queue  # type: ignore[attr-defined]
            ):
                raise QueueFullError(
                    f"client queue full (limit={self.max_client_queue})"
                )

            sub_id = self._next_subscription_id
            self._next_subscription_id += 1
            sub = Subscription(sub_id, conn.id, pattern)  # type: ignore[attr-defined]

            if is_wildcard(pattern):
                prefix = wildcard_prefix(pattern)
                self._wild_subscriptions.setdefault(prefix, {})[sub_id] = sub
            else:
                self._exact_subscriptions.setdefault(pattern, {})[sub_id] = sub
            conn.subscriptions[pattern] = sub  # type: ignore[attr-defined]

            # Backfill only unseen retained history.  The list is already in
            # global sequence order.
            for message in new_backlog:
                conn.enqueue_message((sub.id,), message)  # type: ignore[attr-defined]
            return sub_id

    def unsubscribe(self, conn: "object", pattern: bytes) -> bool:
        try:
            validate_topic(pattern, allow_wildcard=True)
        except InvalidTopicError as exc:
            raise BrokerError(str(exc)) from exc

        with self._lock:
            if pattern not in conn.subscriptions:  # type: ignore[attr-defined]
                return False
            self._remove_subscription(conn, pattern)  # type: ignore[arg-type]
            return True

    def _remove_subscription(self, conn: "object", pattern: bytes) -> None:
        sub = conn.subscriptions.pop(pattern, None)  # type: ignore[attr-defined]
        if sub is None:
            return
        if is_wildcard(pattern):
            prefix = wildcard_prefix(pattern)
            bucket = self._wild_subscriptions.get(prefix)
        else:
            bucket = self._exact_subscriptions.get(pattern)
        conn.remove_pending_subscription(sub.id)  # type: ignore[attr-defined]
        if bucket is not None:
            bucket.pop(sub.id, None)
            if not bucket:
                table = self._wild_subscriptions if is_wildcard(pattern) else self._exact_subscriptions
                table.pop(prefix if is_wildcard(pattern) else pattern, None)

    def _retained_for(self, pattern: bytes) -> List[StoredMessage]:
        if not is_wildcard(pattern):
            return list(self._retained.get(pattern, ()))

        prefix = wildcard_prefix(pattern)
        if prefix == b"":
            return [message for queue in self._retained.values() for message in queue]

        result: List[StoredMessage] = []
        for topic, queue in self._retained.items():
            if topic_matches_prefix(topic, prefix):
                result.extend(queue)
        return result

    # ------------------------------------------------------------------ admin
    def flush(self) -> None:
        with self._lock:
            self.aof.flush()
            self._retained.clear()
            self._next_sequence = 1
            self._published_total = 0
            for conn in self._connections.values():
                conn.clear_pending()  # type: ignore[attr-defined]

    def stats(self) -> Dict[str, int]:
        with self._lock:
            retained_count = sum(len(queue) for queue in self._retained.values())
            subscriber_count = sum(
                len(bucket)
                for table in (self._exact_subscriptions, self._wild_subscriptions)
                for bucket in table.values()
            )
            pending_count = sum(conn.pending_count() for conn in self._connections.values())  # type: ignore[attr-defined]
            return {
                "topics": len(self._retained),
                "retained_messages": retained_count,
                "subscriptions": subscriber_count,
                "connections": len(self._connections),
                "pending_messages": pending_count,
                "next_sequence": self._next_sequence,
                "published_total": self._published_total,
                "retention_limit": self.retention_limit,
                "max_client_queue": self.max_client_queue,
            }
