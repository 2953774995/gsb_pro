"""Broker core: state, command handling and publish/fan-out semantics.

The core is deliberately transport agnostic (``server.py`` wires it to TCP
sockets). All mutable state is guarded by a single re-entrant lock, which
makes "AOF write order == execution order == delivery order" straightforward
to reason about.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Deque, Dict, List, Optional

from .persistence import AppendOnlyLog
from .protocol import (
    bye,
    error,
    integer,
    message as encode_message,
    ok,
    pong,
    stats_reply,
    validate_topic,
)
from .storage import Message, MessageStore
from .subscriptions import SubscriptionTable

DROP_OLDEST = "drop-oldest"
ERROR = "error"
BLOCK = "block"
OVERFLOW_POLICIES = (DROP_OLDEST, ERROR, BLOCK)

# Sentinel queued on a connection's outbox to ask its writer thread to stop.
_SHUTDOWN_SENTINEL = object()


class ClientConnection:
    """Server-side state for one TCP connection."""

    __slots__ = (
        "id",
        "subscriptions",
        "outbox",
        "alive",
        "closed",
        "delivered",
        "dropped",
        "peer",
    )

    def __init__(self, conn_id: int, peer: str = "") -> None:
        self.id = conn_id
        self.peer = peer
        self.subscriptions: set = set()
        self.outbox: Deque[object] = deque()
        # alive=False means "shutting down, no fresh fan-out"; closed=True
        # means the transport tore the connection down.
        self.alive = True
        self.closed = False
        self.delivered = 0
        self.dropped = 0


class Broker:
    def __init__(
        self,
        aof_path: str = ".broker.aof",
        retain: int = 1000,
        max_command_size: int = 1024 * 1024,
        queue_size: int = 10000,
        overflow: str = DROP_OLDEST,
        block_timeout: float = 30.0,
        fsync: bool = False,
    ) -> None:
        if overflow not in OVERFLOW_POLICIES:
            raise ValueError("overflow must be one of %r" % (OVERFLOW_POLICIES,))
        if retain < 0:
            raise ValueError("retain must be >= 0")
        self.aof_path = aof_path
        self.retain = retain
        self.max_command_size = max_command_size
        self.queue_size = queue_size
        self.overflow = overflow
        self.block_timeout = block_timeout

        self.lock = threading.RLock()
        self._cv = threading.Condition(self.lock)
        self._seq = 0
        self.published_count = 0
        self.rejected_count = 0
        self.store = MessageStore(retain=retain)
        self.subscriptions = SubscriptionTable()
        self.connections: Dict[int, ClientConnection] = {}
        self._next_conn_id = 1
        self.aof = AppendOnlyLog(aof_path, fsync=fsync)
        self.shutdown_event = threading.Event()
        self._restore()

    # ------------------------------------------------------------------ #
    # lifecycle / persistence
    # ------------------------------------------------------------------ #
    def start(self) -> None:
        self.aof.open_for_append()

    def close(self) -> None:
        with self.lock:
            self.aof.close()

    def _restore(self) -> None:
        messages, max_seq = AppendOnlyLog.recover(self.aof_path)
        for msg in messages:
            self.store.append(msg)
        self._seq = max_seq

    # ------------------------------------------------------------------ #
    # connection registry
    # ------------------------------------------------------------------ #
    def add_connection(self, peer: str = "") -> ClientConnection:
        with self.lock:
            conn = ClientConnection(self._next_conn_id, peer=peer)
            self._next_conn_id += 1
            self.connections[conn.id] = conn
            return conn

    def remove_connection(self, conn: ClientConnection) -> None:
        with self.lock:
            if conn.closed:
                return
            conn.closed = True
            conn.alive = False
            self.subscriptions.remove_connection(conn)
            self.connections.pop(conn.id, None)
            # Do not clear the outbox here: the writer may still need to flush
            # a queued +BYE or error frame before closing the socket.
            self._cv.notify_all()

    def drain_outbox(self, conn: ClientConnection) -> Optional[List[object]]:
        """Atomically take everything queued for a connection."""
        with self.lock:
            while not conn.outbox and not conn.closed:
                self._cv.wait(timeout=0.5)
            if not conn.outbox:
                return None
            batch: List[object] = []
            while conn.outbox:
                batch.append(conn.outbox.popleft())
            return batch

    def on_batch_sent(self, conn: ClientConnection) -> None:
        with self.lock:
            conn.delivered += 1
            self._cv.notify_all()

    # ------------------------------------------------------------------ #
    # commands
    # ------------------------------------------------------------------ #
    def handle_ping(self, conn: ClientConnection) -> bytes:
        return pong()

    def handle_subscribe(self, conn: ClientConnection, pattern: str) -> bytes:
        with self.lock:
            added = self.subscriptions.subscribe(conn, pattern)
            if added:
                # Replay retained history first, in global sequence order, so
                # a new subscriber sees past messages before live ones.
                backlog = self.store.replay(pattern)
                for msg in backlog:
                    self._enqueue_locked(
                        conn, encode_message(msg.topic, msg.seq, msg.payload)
                    )
            return ok("SUBSCRIBED %s" % pattern)

    def handle_unsubscribe(self, conn: ClientConnection, pattern: str) -> bytes:
        with self.lock:
            removed = self.subscriptions.unsubscribe(conn, pattern)
            if not removed:
                return error("not subscribed to %s" % pattern)
            return ok("UNSUBSCRIBED %s" % pattern)

    def handle_publish(
        self, conn: Optional[ClientConnection], topic: str, payload: bytes
    ) -> bytes:
        validate_topic(topic)
        with self.lock:
            targets = self.subscriptions.subscribers_of(topic)

            if self.overflow == ERROR:
                for target in targets:
                    if len(target.outbox) >= self.queue_size:
                        self.rejected_count += 1
                        return error(
                            "queue full for a subscriber of '%s' (limit %d)"
                            % (topic, self.queue_size)
                        )
            elif self.overflow == BLOCK:
                deadline = time.monotonic() + self.block_timeout
                while True:
                    if self.shutdown_event.is_set():
                        self.rejected_count += 1
                        return error("broker is shutting down")
                    full = [
                        target
                        for target in targets
                        if len(target.outbox) >= self.queue_size
                    ]
                    if not full:
                        break
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        self.rejected_count += 1
                        return error("publish timed out: subscriber queues full")
                    self._cv.wait(timeout=remaining)

            self._seq += 1
            seq = self._seq
            stored = Message(seq=seq, topic=topic, payload=payload)

            # Execution order: 1) persist, 2) retain, 3) fan out.
            self.aof.append_message(stored)
            self.store.append(stored)
            self.published_count += 1
            for target in targets:
                self._enqueue_locked(
                    target, encode_message(topic, seq, payload)
                )
            self._cv.notify_all()
            return integer(seq)

    def handle_flush(self, conn: ClientConnection) -> bytes:
        with self.lock:
            self.store.clear()
            self.aof.truncate()
            self._seq = 0
            self.published_count = 0
            self.rejected_count = 0
            self._cv.notify_all()
            return ok("FLUSHED")

    def handle_stats(self, conn: ClientConnection) -> bytes:
        with self.lock:
            pending = sum(len(c.outbox) for c in self.connections.values())
            items = [
                ("seq", self._seq),
                ("published", self.published_count),
                ("rejected", self.rejected_count),
                ("retained", self.store.total_messages()),
                ("topics", self.store.topic_count()),
                ("connections", len(self.connections)),
                ("subscriptions", self.subscriptions.subscription_count()),
                ("patterns", self.subscriptions.pattern_count()),
                ("pending_delivery", pending),
                ("retain", self.retain),
                ("queue_size", self.queue_size),
                ("overflow", self.overflow),
            ]
            return stats_reply(items)

    def shutdown(self) -> None:
        """Begin graceful shutdown: send +BYE to every connected client."""
        with self.lock:
            if self.shutdown_event.is_set():
                return
            self.shutdown_event.set()
            frame = bye("server shutting down")
            for conn in list(self.connections.values()):
                conn.alive = False
                # Bypass the alive check: the goodbye must reach the wire.
                conn.outbox.append(frame)
                conn.outbox.append(_SHUTDOWN_SENTINEL)
            self._cv.notify_all()

    # ------------------------------------------------------------------ #
    # delivery helpers
    # ------------------------------------------------------------------ #
    def _enqueue_locked(self, conn: ClientConnection, frame: bytes) -> None:
        if not conn.alive or conn.closed:
            conn.dropped += 1
            return
        if len(conn.outbox) >= self.queue_size:
            if self.overflow == DROP_OLDEST:
                evicted = conn.outbox.popleft()
                if evicted is not _SHUTDOWN_SENTINEL:
                    conn.dropped += 1
            else:
                # ERROR pre-rejects and BLOCK waits, so this is defensive.
                conn.dropped += 1
                return
        conn.outbox.append(frame)
