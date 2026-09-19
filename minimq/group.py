"""Consumer group state: dispatch, in-flight tracking and ack watermark."""

import heapq
import json
import os
import threading

from .errors import MqError


class ConsumerGroup(object):
    """Tracks consumption of one topic by one named group.

    Semantics:
      * Messages are dispatched to exactly one consumer of the group
        (load balancing); different groups are fully independent.
      * Delivered-but-unacked messages are "in-flight" and owned by the
        consumer that polled them. Re-polling the same consumer
        redelivers its own unacked messages; closing a consumer returns
        them to the group's pending pool for redelivery to others.
      * ``committed`` is the contiguous ack watermark: all offsets below
        it are acknowledged. It is persisted so a restart never
        redelivers acknowledged messages.
    """

    def __init__(self, topic_name, group_name, store_path=None):
        self.topic_name = topic_name
        self.group_name = group_name
        self._store_path = store_path
        self._lock = threading.RLock()
        self.committed = 0        # next offset known to be fully acked
        self._next_fetch = 0      # next offset never dispatched yet
        self._inflight = {}       # offset -> consumer_id
        self._pending = []        # min-heap of released offsets to redeliver
        self._acked_ahead = set() # acked offsets beyond the watermark
        if store_path and os.path.exists(store_path):
            try:
                with open(store_path, "r", encoding="utf-8") as f:
                    state = json.load(f)
                self.committed = int(state.get("committed", 0))
            except (ValueError, OSError):
                self.committed = 0
            self._next_fetch = self.committed

    # -- polling ---------------------------------------------------------

    def poll(self, consumer_id, topic, max_messages):
        """Collect up to ``max_messages`` offsets for ``consumer_id``.

        Returns a list of ``(offset, body)`` tuples.
        """
        if max_messages < 1:
            raise MqError("max_messages must be >= 1, got %r" % (max_messages,))
        with self._lock:
            base = topic.base_offset
            if self._next_fetch < base:
                self._next_fetch = base
            if self.committed < base:
                # Retention dropped messages that were never acked; the
                # watermark can only move forward.
                self.committed = base
                self._save()

            offsets = []
            # 1. Redeliver this consumer's own unacked messages.
            for offset in sorted(self._inflight):
                if len(offsets) >= max_messages:
                    break
                if self._inflight[offset] == consumer_id:
                    offsets.append(offset)
            # 2. Redeliver messages released by other (closed) consumers.
            while self._pending and len(offsets) < max_messages:
                offset = heapq.heappop(self._pending)
                if offset in self._inflight or offset < self.committed:
                    continue
                if offset < base:
                    continue
                self._inflight[offset] = consumer_id
                offsets.append(offset)
            # 3. Dispatch fresh messages.
            while (len(offsets) < max_messages
                   and self._next_fetch < topic.next_offset):
                offset = self._next_fetch
                self._next_fetch += 1
                self._inflight[offset] = consumer_id
                offsets.append(offset)

            messages = []
            for offset in offsets:
                body = topic.get(offset)
                if body is None:
                    # Dropped by retention while in-flight: forget it.
                    self._inflight.pop(offset, None)
                    continue
                messages.append((offset, body))
            return messages

    # -- acking -----------------------------------------------------------

    def ack(self, consumer_id, offset):
        with self._lock:
            owner = self._inflight.get(offset)
            if owner is None:
                raise MqError(
                    "cannot ack offset %d in group %r: it was not delivered "
                    "or is already acknowledged" % (offset, self.group_name))
            if owner != consumer_id:
                raise MqError(
                    "cannot ack offset %d in group %r: it is owned by "
                    "another consumer" % (offset, self.group_name))
            del self._inflight[offset]
            if offset == self.committed:
                self.committed += 1
                while self.committed in self._acked_ahead:
                    self._acked_ahead.discard(self.committed)
                    self.committed += 1
                self._save()
            elif offset > self.committed:
                self._acked_ahead.add(offset)
            # offset < committed cannot happen for an in-flight offset.

    # -- consumer lifecycle -------------------------------------------------

    def release(self, consumer_id):
        """Return all of the consumer's unacked messages to the pool."""
        with self._lock:
            for offset in sorted(self._inflight):
                if self._inflight[offset] == consumer_id:
                    del self._inflight[offset]
                    if offset >= self.committed:
                        heapq.heappush(self._pending, offset)

    # -- persistence ---------------------------------------------------------

    def _save(self):
        if not self._store_path:
            return
        directory = os.path.dirname(self._store_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        tmp_path = self._store_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump({"topic": self.topic_name,
                       "group": self.group_name,
                       "committed": self.committed}, f)
        os.replace(tmp_path, self._store_path)
