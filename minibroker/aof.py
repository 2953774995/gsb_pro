"""Append-only file persistence.

Every PUBLISH is appended before the in-memory state is updated, so the
file order always matches execution order.  Records:

    PUBLISH <seq> <topic> <len>\n<payload>\n   a published message
    SEQ <next-seq>\n                           written by FLUSH so the
                                               sequence survives a restart
"""

import os
import threading

from . import protocol

# Recovery accepts frames far larger than the runtime command limit.
_RECOVERY_MAX_FRAME = 64 * 1024 * 1024


class AOF:
    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()
        self._file = open(path, "ab")

    def append_publish(self, seq, topic, payload):
        record = b"PUBLISH %d %s %d\n" % (seq, topic.encode("utf-8"), len(payload))
        record += payload + b"\n"
        with self._lock:
            self._file.write(record)
            self._file.flush()

    def append_seq(self, next_seq):
        with self._lock:
            self._file.write(b"SEQ %d\n" % next_seq)
            self._file.flush()

    def reset(self):
        """Truncate the file (used by FLUSH)."""
        with self._lock:
            self._file.close()
            open(self.path, "wb").close()
            self._file = open(self.path, "ab")

    def close(self):
        with self._lock:
            if not self._file.closed:
                self._file.flush()
                self._file.close()

    @staticmethod
    def load(path):
        """Replay the file. Returns (entries, next_seq).

        entries is a list of (seq, topic, payload) in file order.  A torn
        tail record (crash mid-write) is ignored.
        """
        entries = []
        next_seq = 1
        if not os.path.exists(path):
            return entries, next_seq
        with open(path, "rb") as stream:
            while True:
                try:
                    tokens, payload = protocol.read_frame(
                        stream, max_command=_RECOVERY_MAX_FRAME
                    )
                except (EOFError, protocol.ProtocolError):
                    break
                command = tokens[0].upper()
                if command == "PUBLISH" and len(tokens) == 4 and payload is not None:
                    seq = int(tokens[1])
                    entries.append((seq, tokens[2], payload))
                    next_seq = max(next_seq, seq + 1)
                elif command == "SEQ" and len(tokens) == 2:
                    next_seq = max(next_seq, int(tokens[1]))
                else:
                    raise ValueError("corrupt AOF record: %r" % (tokens,))
        return entries, next_seq
