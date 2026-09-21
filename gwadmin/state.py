"""Thread-safe runtime state."""

import threading
import time

from .constants import VERSION


class RuntimeState:
    def __init__(self):
        self.started_at = time.monotonic()
        self._lock = threading.Lock()
        self.requests_handled = 0
        self.worker_count = 1

    def set_workers(self, count):
        self.worker_count = int(count)

    def count_request(self):
        with self._lock:
            self.requests_handled += 1

    def snapshot(self):
        with self._lock:
            requests_handled = self.requests_handled
        return {
            "uptime_seconds": max(0.0, time.monotonic() - self.started_at),
            "version": VERSION,
            "worker_threads": self.worker_count,
            "requests_handled": requests_handled,
        }
