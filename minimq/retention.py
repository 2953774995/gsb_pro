"""Retention policy for topics.

At least one of two limits may be configured:

* ``max_messages`` - keep at most this many messages;
* ``max_bytes``    - keep at most this many payload bytes.

Whenever a topic exceeds a configured limit the oldest messages
(lowest offsets) are dropped first. Both limits may be combined.
"""

from .errors import MqError


class RetentionPolicy:
    def __init__(self, max_messages=None, max_bytes=None):
        if max_messages is not None and (
            not isinstance(max_messages, int) or max_messages <= 0
        ):
            raise MqError("max_messages must be a positive integer or None")
        if max_bytes is not None and (
            not isinstance(max_bytes, int) or max_bytes <= 0
        ):
            raise MqError("max_bytes must be a positive integer or None")
        if max_messages is None and max_bytes is None:
            # No retention at all is valid - callers default to unlimited.
            pass
        self.max_messages = max_messages
        self.max_bytes = max_bytes

    def is_over_limit(self, message_count, total_bytes):
        if self.max_messages is not None and message_count > self.max_messages:
            return True
        if self.max_bytes is not None and total_bytes > self.max_bytes:
            return True
        return False

    def enforce(self, ordered_offsets, size_of):
        """Return offsets that must be evicted.

        ``ordered_offsets`` is an iterable of offsets sorted oldest-first.
        ``size_of`` maps an offset to its payload size. Eviction proceeds
        from the oldest offset until neither limit is violated.
        """
        offsets = list(ordered_offsets)
        count = len(offsets)
        total = sum(size_of(o) for o in offsets)
        evict = []
        i = 0
        while i < len(offsets) and self.is_over_limit(count, total):
            evict.append(offsets[i])
            total -= size_of(offsets[i])
            count -= 1
            i += 1
        return evict

    def to_dict(self):
        return {"max_messages": self.max_messages, "max_bytes": self.max_bytes}

    @classmethod
    def from_dict(cls, data):
        data = data or {}
        return cls(
            max_messages=data.get("max_messages"),
            max_bytes=data.get("max_bytes"),
        )

    def enabled(self):
        return self.max_messages is not None or self.max_bytes is not None

    def __repr__(self):
        return "RetentionPolicy(max_messages={!r}, max_bytes={!r})".format(
            self.max_messages, self.max_bytes
        )
