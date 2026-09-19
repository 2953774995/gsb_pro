"""Python client SDK for minibroker."""

import queue
import socket
import threading

from . import protocol


class BrokerServerError(Exception):
    """The broker replied with -ERR."""


class BrokerClient:
    def __init__(self, host="127.0.0.1", port=7379, timeout=10.0,
                 max_command=protocol.DEFAULT_MAX_COMMAND):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.max_command = max_command
        self._sock = None
        self._stream = None
        self._reader = None
        self._call_lock = threading.Lock()
        self._replies = queue.Queue()
        self._messages = queue.Queue()

    # -- lifecycle -------------------------------------------------------

    def connect(self):
        self._sock = socket.create_connection(
            (self.host, self.port), timeout=self.timeout)
        self._sock.settimeout(None)
        self._stream = self._sock.makefile("rb")
        self._reader = threading.Thread(
            target=self._read_loop, name="broker-client-reader", daemon=True)
        self._reader.start()
        return self

    def close(self):
        if self._sock is not None:
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def __enter__(self):
        return self.connect()

    def __exit__(self, *exc_info):
        self.close()

    # -- background reader ------------------------------------------------

    def _read_loop(self):
        try:
            while True:
                tokens, payload = protocol.read_frame(
                    self._stream, self.max_command)
                head = tokens[0]
                if head == "MSG":
                    self._messages.put((int(tokens[1]), tokens[2], payload))
                elif head == "+BYE":
                    continue  # informational; EOF follows
                elif head.startswith("+") or head.startswith("-"):
                    self._replies.put(tokens)
        except (EOFError, OSError, protocol.ProtocolError):
            pass
        finally:
            self._replies.put(None)
            self._messages.put(None)

    def _call(self, command, args=(), payload=None):
        if self._sock is None:
            raise ConnectionError("not connected")
        with self._call_lock:
            self._sock.sendall(
                protocol.encode_command(command, args, payload))
            tokens = self._replies.get()
        if tokens is None:
            raise ConnectionError("connection closed by broker")
        if tokens[0] == "-ERR":
            raise BrokerServerError(" ".join(tokens[1:]))
        return tokens

    # -- API ---------------------------------------------------------------

    def ping(self):
        return self._call("PING")[0] == "+PONG"

    def publish(self, topic, payload):
        """Publish bytes/str payload; returns the global sequence number."""
        tokens = self._call("PUBLISH", [topic], payload)
        return int(tokens[1])

    def subscribe(self, pattern):
        self._call("SUBSCRIBE", [pattern])

    def unsubscribe(self, pattern):
        self._call("UNSUBSCRIBE", [pattern])

    def stats(self):
        tokens = self._call("STATS")
        result = {}
        for item in tokens[1:]:
            key, _, value = item.partition("=")
            result[key] = int(value)
        return result

    def flush(self):
        self._call("FLUSH")

    def shutdown(self):
        self._call("SHUTDOWN")

    def next_message(self, timeout=None):
        """Block until the next pushed message arrives.

        Returns (seq, topic, payload) or None on timeout / disconnect.
        """
        try:
            item = self._messages.get(timeout=timeout)
        except queue.Empty:
            return None
        return item
