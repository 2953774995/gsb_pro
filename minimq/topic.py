"""Topic: an ordered, offset-addressed sequence of messages."""

import json
import os
import threading

from .errors import MqError
from .storage import RecordLog


class Topic(object):
    """A named message log with optional retention.

    Offsets are monotonically increasing and start at 0. Retention drops
    the oldest messages but never rewinds ``next_offset``, so consumer
    offsets stay meaningful across cleanup and restarts.
    """

    def __init__(self, name, log_path=None, meta_path=None,
                 max_messages=None, max_bytes=None, fsync=True):
        if max_messages is not None and max_messages < 1:
            raise MqError("max_messages must be >= 1, got %r" % (max_messages,))
        if max_bytes is not None and max_bytes < 1:
            raise MqError("max_bytes must be >= 1, got %r" % (max_bytes,))
        self.name = name
        self.max_messages = max_messages
        self.max_bytes = max_bytes
        self._fsync = fsync
        self._lock = threading.RLock()
        self._messages = []  # list of (offset, body), offset ascending
        self._next_offset = 0
        self._size_bytes = 0
        self._meta_path = meta_path
        self._log = RecordLog(log_path) if log_path else None
        if self._log is not None:
            self._messages = self._log.load()
            for _, body in self._messages:
                self._size_bytes += len(body.encode("utf-8"))
            if self._messages:
                self._next_offset = self._messages[-1][0] + 1

    # -- properties ----------------------------------------------------

    @property
    def next_offset(self):
        """Offset the next published message will get."""
        with self._lock:
            return self._next_offset

    @property
    def base_offset(self):
        """Oldest offset still available (== next_offset when empty)."""
        with self._lock:
            if self._messages:
                return self._messages[0][0]
            return self._next_offset

    @property
    def size(self):
        with self._lock:
            return len(self._messages)

    # -- core operations ------------------------------------------------

    def append(self, body):
        """Append ``body`` and return its offset."""
        with self._lock:
            offset = self._next_offset
            if self._log is not None:
                self._log.append(offset, body, fsync=self._fsync)
            self._messages.append((offset, body))
            self._next_offset += 1
            self._size_bytes += len(body.encode("utf-8"))
            self._enforce_retention()
            return offset

    def get(self, offset):
        """Return the body at ``offset`` or None if it was discarded."""
        with self._lock:
            if not self._messages:
                return None
            index = offset - self._messages[0][0]
            if index < 0 or index >= len(self._messages):
                return None
            return self._messages[index][1]

    # -- retention -------------------------------------------------------

    def _enforce_retention(self):
        dropped = False
        while (self.max_messages is not None
               and len(self._messages) > self.max_messages):
            self._drop_oldest()
            dropped = True
        while (self.max_bytes is not None
               and self._size_bytes > self.max_bytes
               and len(self._messages) > 1):
            self._drop_oldest()
            dropped = True
        if dropped and self._log is not None:
            # Compact the on-disk log so dropped messages stay dropped
            # after a restart.
            self._log.rewrite(self._messages, fsync=self._fsync)

    def _drop_oldest(self):
        _, body = self._messages.pop(0)
        self._size_bytes -= len(body.encode("utf-8"))

    # -- metadata persistence --------------------------------------------

    def save_meta(self):
        if self._meta_path is None:
            return
        meta = {"name": self.name,
                "max_messages": self.max_messages,
                "max_bytes": self.max_bytes}
        tmp_path = self._meta_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(meta, f)
        os.replace(tmp_path, self._meta_path)

    @classmethod
    def recover(cls, topic_dir, fsync=True):
        """Rebuild a topic from its on-disk directory."""
        log_path = os.path.join(topic_dir, "messages.log")
        meta_path = os.path.join(topic_dir, "meta.json")
        name = os.path.basename(topic_dir)
        max_messages = max_bytes = None
        if os.path.exists(meta_path):
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                name = meta.get("name", name)
                max_messages = meta.get("max_messages")
                max_bytes = meta.get("max_bytes")
            except (ValueError, OSError):
                pass  # fall back to defaults; the log is the source of truth
        return cls(name, log_path=log_path, meta_path=meta_path,
                   max_messages=max_messages, max_bytes=max_bytes,
                   fsync=fsync)

    def close(self):
        if self._log is not None:
            self._log.close()
