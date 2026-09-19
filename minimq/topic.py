"""Topic: an append-only stream of messages with per-topic retention."""

import collections

from .errors import MessageTooLargeError, MqError
from .retention import RetentionPolicy
from .storage import LogStorage

DEFAULT_MAX_MESSAGE_SIZE = 1024 * 1024  # 1 MiB


class Topic:
    """Owns the in-memory message window and the on-disk log.

    Concurrency: every public method assumes the broker-wide lock is held.
    """

    def __init__(
        self,
        name,
        log_path,
        retention=None,
        max_message_size=DEFAULT_MAX_MESSAGE_SIZE,
        fsync=True,
        on_evict=None,
    ):
        self.name = name
        self.log_path = log_path
        self.retention = retention or RetentionPolicy()
        self.max_message_size = max_message_size
        self._on_evict = on_evict

        self._messages = collections.OrderedDict()  # offset -> payload bytes
        self._next_offset = 0

        self.log = LogStorage(log_path, fsync=fsync)
        self._recover()

    # ------------------------------------------------------------------
    # recovery
    # ------------------------------------------------------------------
    def _recover(self):
        records, _ = self.log.recover()
        expected = None
        for offset, payload in records:
            # Records are contiguous, but the first offset may be > 0 after
            # retention compaction rewrote the log.
            if expected is None:
                expected = offset
            elif offset != expected:
                raise MqError(
                    "corrupt log for topic {!r}: expected offset {}, found {}".format(
                        self.name, expected, offset
                    )
                )
            self._messages[offset] = payload
            self._next_offset = offset + 1
            expected += 1

    # ------------------------------------------------------------------
    # publishing
    # ------------------------------------------------------------------
    def publish(self, payload):
        if not isinstance(payload, (bytes, bytearray)):
            raise TypeError("message payload must be bytes")
        if len(payload) > self.max_message_size:
            raise MessageTooLargeError(
                "message of {} bytes exceeds max_message_size {} for topic {!r}".format(
                    len(payload), self.max_message_size, self.name
                )
            )
        offset = self._next_offset
        self.log.append(offset, bytes(payload))
        self._messages[offset] = bytes(payload)
        self._next_offset += 1
        self._enforce_retention()
        return offset

    # ------------------------------------------------------------------
    # retention
    # ------------------------------------------------------------------
    def _enforce_retention(self):
        if not self.retention.enabled():
            return
        evicted = self.retention.enforce(
            list(self._messages.keys()), lambda o: len(self._messages[o])
        )
        if not evicted:
            return
        for o in evicted:
            del self._messages[o]
        if self._on_evict is not None:
            self._on_evict(self.name, evicted)
        # Compact the on-disk log so it cannot grow without bound.
        self.log.rewrite(list(self._messages.items()))

    # ------------------------------------------------------------------
    # views
    # ------------------------------------------------------------------
    def earliest_offset(self):
        try:
            return next(iter(self._messages))
        except StopIteration:
            return self._next_offset

    def next_offset(self):
        return self._next_offset

    def latest_offset(self):
        return self._next_offset - 1

    def log_start_offset(self):
        """Smallest offset still available in the log."""
        return self.earliest_offset()

    def size_bytes(self):
        return sum(len(p) for p in self._messages.values())

    def __len__(self):
        return len(self._messages)

    def __contains__(self, offset):
        return offset in self._messages

    def get(self, offset):
        return self._messages.get(offset)

    def offsets(self):
        return list(self._messages.keys())

    def snapshot(self):
        return list(self._messages.items())

    def config_dict(self):
        return {
            "max_message_size": self.max_message_size,
            "retention": self.retention.to_dict(),
        }

    def close(self):
        self.log.close()
