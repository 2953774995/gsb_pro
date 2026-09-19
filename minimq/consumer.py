"""Consumer groups, polling consumers and per-group offset persistence."""

import dataclasses
import itertools
import json
import os
import weakref

from .errors import ConsumerGroupError, MqError, TopicNotFoundError

_SAFE = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._~"
)


def _sanitize(name):
    """Percent-encode anything that is not URL-unreserved (path safe)."""
    out = []
    for ch in name:
        if ch in _SAFE:
            out.append(ch)
        else:
            for b in ch.encode("utf-8"):
                out.append("%{:02X}".format(b))
    return "".join(out)


@dataclasses.dataclass(frozen=True)
class Message:
    """A delivered message."""

    offset: int
    value: bytes


def _finalize_consumer(broker, group, cid):
    """Release inflight leases if a Consumer is garbage collected without
    an explicit close(), so messages can never get stuck forever."""
    try:
        with broker.lock:
            if not getattr(broker, "_closed", False):
                group.release_consumer(cid)
    except Exception:
        # Never let GC-time cleanup raise.
        pass


class ConsumerGroup:
    """Shared state of every consumer subscribed under one group name.

    Persistent state (``groups/`` directory, one JSON file per
    topic+group)::

        {
          "hwm": 5,            # every offset < hwm has been acked
          "gaps": [7, 9]       # acked offsets >= hwm (out-of-order acks)
        }

    Transient in-memory state:

    * ``inflight``: ``offset -> consumer_id`` for messages that were
      delivered via poll but not acked yet;
    * ``consumers``: live ``Consumer`` objects (weak references).

    Load-balancing semantics: a poll by any consumer of the group pulls
    from the shared pool of available offsets, so two consumers in the
    same group can never be handed the same offset concurrently.
    Different groups keep independent state and each see the full stream.
    """

    def __init__(self, topic_name, group_name, state_dir, broker):
        self.topic_name = topic_name
        self.group_name = group_name
        self._broker = broker
        # "!" never occurs in a sanitized name (it is percent-encoded),
        # so the file name can be parsed unambiguously.
        self.state_path = os.path.join(
            state_dir,
            "{}!{}.json".format(_sanitize(topic_name), _sanitize(group_name)),
        )
        self.hwm = 0
        self.gaps = set()
        self.inflight = {}              # offset -> consumer_id
        self.consumers = weakref.WeakValueDictionary()  # cid -> Consumer
        self._cid_seq = itertools.count(1)
        self._load()

    # ------------------------------------------------------------------
    # persistence
    # ------------------------------------------------------------------
    def _load(self):
        if not os.path.exists(self.state_path):
            return
        with open(self.state_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.hwm = int(data.get("hwm", 0))
        self.gaps = set(int(o) for o in data.get("gaps", []))

    def _persist(self):
        data = {"hwm": self.hwm, "gaps": sorted(self.gaps)}
        directory = os.path.dirname(self.state_path)
        tmp = "{}.tmp".format(self.state_path)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, separators=(",", ":"))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.state_path)

    # ------------------------------------------------------------------
    # retention support
    # ------------------------------------------------------------------
    def evict_offsets(self, offsets):
        """Forget state for offsets removed by retention.

        Evicted messages must never be redelivered, so the group high
        water mark is advanced past them.
        """
        changed = False
        for o in offsets:
            if o in self.gaps:
                self.gaps.discard(o)
                changed = True
            if self.inflight.pop(o, None) is not None:
                changed = True
            if o >= self.hwm:
                self.hwm = o + 1
                changed = True
        if changed:
            self._persist()

    # ------------------------------------------------------------------
    # consumer registry
    # ------------------------------------------------------------------
    def register(self, consumer):
        cid = next(self._cid_seq)
        self.consumers[cid] = consumer
        return cid

    def release_consumer(self, cid):
        """Return all inflight offsets owned by a closing consumer."""
        released = [o for o, owner in self.inflight.items() if owner == cid]
        for o in released:
            del self.inflight[o]
        self.consumers.pop(cid, None)
        return released

    # ------------------------------------------------------------------
    # polling
    # ------------------------------------------------------------------
    def poll(self, consumer, max_messages):
        if max_messages is None:
            max_messages = 1
        if not isinstance(max_messages, int) or max_messages <= 0:
            raise MqError("max_messages must be a positive integer")
        topic = self._broker._topic(self.topic_name)
        cid = consumer.cid
        out = []
        for offset in list(topic.offsets()):
            if len(out) >= max_messages:
                break
            if offset < self.hwm or offset in self.gaps:
                continue  # already acknowledged
            if offset in self.inflight:
                continue  # delivered to some consumer, awaiting ack
            self.inflight[offset] = cid
            out.append(Message(offset=offset, value=topic.get(offset)))
        return out

    # ------------------------------------------------------------------
    # acknowledgement
    # ------------------------------------------------------------------
    def ack(self, consumer, offset):
        if not isinstance(offset, int) or offset < 0:
            raise MqError("offset must be a non-negative integer, got {!r}".format(offset))
        topic = self._broker._topic(self.topic_name)

        if offset < topic.log_start_offset():
            raise ConsumerGroupError(
                "cannot ack offset {} for topic {!r}: offset already dropped by "
                "retention (log start offset {})".format(
                    offset, self.topic_name, topic.log_start_offset()
                )
            )
        if offset not in topic:
            raise TopicNotFoundError(
                "offset {} does not exist in topic {!r} (next offset {})".format(
                    offset, self.topic_name, topic.next_offset()
                )
            )
        if offset < self.hwm or offset in self.gaps:
            raise ConsumerGroupError(
                "duplicate ack: offset {} already acknowledged for group {!r} "
                "on topic {!r}".format(offset, self.group_name, self.topic_name)
            )
        owner = self.inflight.get(offset)
        if owner is None:
            raise ConsumerGroupError(
                "offset {} was never delivered to consumer {!r} (group {!r} on "
                "topic {!r}); poll before ack".format(
                    offset, consumer.cid, self.group_name, self.topic_name
                )
            )
        if owner != consumer.cid:
            raise ConsumerGroupError(
                "offset {} is inflight on consumer {} but acked by consumer {}".format(
                    offset, owner, consumer.cid
                )
            )

        del self.inflight[offset]
        if offset == self.hwm:
            self.hwm += 1
            while self.hwm in self.gaps:
                self.gaps.discard(self.hwm)
                self.hwm += 1
        else:
            self.gaps.add(offset)
        self._persist()
        return offset


class Consumer:
    """Polling handle for one (topic, group) subscription."""

    def __init__(self, group, broker):
        self._group = group
        self._broker = broker
        self.cid = group.register(self)
        self.closed = False
        # Args must not capture ``self`` (that would defeat the weakref).
        self._finalizer = weakref.finalize(
            self, _finalize_consumer, broker, group, self.cid
        )

    @property
    def group_name(self):
        return self._group.group_name

    @property
    def topic_name(self):
        return self._group.topic_name

    def poll(self, max_messages=1):
        """Pull up to ``max_messages`` unacknowledged messages.

        Returns a (possibly empty) list of :class:`Message`. Offsets
        handed out are marked inflight and will not be delivered to
        another consumer of the same group until acked or released.
        """
        with self._broker.lock:
            if self.closed:
                raise MqError("consumer is closed")
            return self._group.poll(self, max_messages)

    def ack(self, offset):
        """Acknowledge a delivered offset; persists group progress."""
        with self._broker.lock:
            if self.closed:
                raise MqError("consumer is closed")
            return self._group.ack(self, offset)

    # ``consume`` is an explicit alias for ack per the PRD wording
    # "consumers consume/ack(offset)".
    def consume(self, offset):
        return self.ack(offset)

    def close(self):
        if self.closed:
            return
        with self._broker.lock:
            if self.closed:
                return
            self._group.release_consumer(self.cid)
            self.closed = True
            self._finalizer.detach()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    def __repr__(self):
        return "Consumer(cid={}, topic={!r}, group={!r})".format(
            self.cid, self.topic_name, self.group_name
        )
