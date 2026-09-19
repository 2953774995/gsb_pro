"""Synchronous Python client SDK for minibroker (standard library only).

A background reader thread demultiplexes incoming frames: asynchronous
``MSG`` pushes go into a message queue consumed by
:meth:`BrokerClient.next_message`, while command responses are matched to
the (single) in-flight command.
"""

from __future__ import annotations

import json
import queue
import socket
import threading

from .protocol import (
    DEFAULT_MAX_COMMAND_SIZE,
    ProtocolError,
    encode_publish,
    encode_simple,
    parse_msg_header,
    read_exact,
    read_line,
)

_CLOSED = object()  # sentinel pushed into queues when the connection drops


class BrokerError(Exception):
    """The server replied with an ERR frame."""


class BrokerClosed(Exception):
    """The connection to the broker was closed (BYE, EOF or network error)."""


class Message:
    """One message delivered to a subscriber."""

    __slots__ = ("seq", "topic", "payload")

    def __init__(self, seq: int, topic: str, payload: bytes):
        self.seq = seq
        self.topic = topic
        self.payload = payload

    @property
    def text(self) -> str:
        return self.payload.decode("utf-8")

    def __repr__(self):
        return "Message(seq=%r, topic=%r, payload=%r)" % (
            self.seq,
            self.topic,
            self.payload,
        )

    def __eq__(self, other):
        return (
            isinstance(other, Message)
            and (self.seq, self.topic, self.payload)
            == (other.seq, other.topic, other.payload)
        )


class BrokerClient:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 7379,
        timeout: float = 10.0,
        max_frame_size: int = DEFAULT_MAX_COMMAND_SIZE + 4096,
    ):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._max_frame = max_frame_size
        self._sock = None
        self._rfile = None
        self._wfile = None
        self._messages: queue.Queue = queue.Queue()
        self._responses: queue.Queue = queue.Queue()
        self._cmd_lock = threading.Lock()
        self._closed = threading.Event()
        self._reader = None

    # -- lifecycle -------------------------------------------------------

    def connect(self, sock: socket.socket | None = None) -> "BrokerClient":
        """Connect to the broker.

        An already-connected *sock* may be supplied (used by tests and by
        callers that want a custom transport); otherwise a TCP connection
        to ``(host, port)`` is established.
        """
        if sock is None:
            self._sock = socket.create_connection(
                (self.host, self.port), timeout=self.timeout
            )
            self._sock.settimeout(None)
            try:
                self._sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except OSError:
                pass
        else:
            self._sock = sock
        self._rfile = self._sock.makefile("rb")
        self._wfile = self._sock.makefile("wb")
        self._reader = threading.Thread(
            target=self._reader_loop, name="mb-client-reader", daemon=True
        )
        self._reader.start()
        return self

    def __enter__(self):
        return self.connect()

    def __exit__(self, *exc):
        self.close()
        return False

    def close(self) -> None:
        self._closed.set()
        # Shutdown first: this wakes the reader thread blocked in read()
        # (closing a makefile object while another thread reads from it
        # would otherwise deadlock on the buffer lock).
        if self._sock is not None:
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        for f in (self._rfile, self._wfile):
            try:
                if f is not None:
                    f.close()
            except OSError:
                pass
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass

    @property
    def closed(self) -> bool:
        return self._closed.is_set()

    # -- reader thread ---------------------------------------------------

    def _reader_loop(self) -> None:
        try:
            while True:
                line = read_line(self._rfile, self._max_frame)
                if line.startswith(b"MSG "):
                    seq, topic, length = parse_msg_header(line)
                    payload = read_exact(self._rfile, length)
                    self._messages.put(Message(seq, topic, payload))
                elif line.startswith(b"STATS "):
                    try:
                        length = int(line[len(b"STATS "):])
                    except ValueError:
                        raise ProtocolError("malformed STATS header")
                    payload = read_exact(self._rfile, length)
                    self._responses.put(("stats", json.loads(payload.decode("utf-8"))))
                elif line.startswith(b"OK"):
                    text = line[2:].strip().decode("utf-8", "replace")
                    self._responses.put(("ok", text))
                elif line.startswith(b"ERR "):
                    self._responses.put(("err", line[4:].decode("utf-8", "replace")))
                elif line == b"PONG":
                    self._responses.put(("pong", None))
                elif line.startswith(b"BYE"):
                    reason = line[3:].strip().decode("utf-8", "replace")
                    self._responses.put(("bye", reason))
                    return
                else:
                    raise ProtocolError("unknown frame %r" % line[:32])
        except (EOFError, OSError, ProtocolError, ValueError):
            pass
        finally:
            self._closed.set()
            self._responses.put(("bye", "connection closed"))
            self._messages.put(_CLOSED)

    # -- command round trip ----------------------------------------------

    def _roundtrip(self, frame: bytes):
        if self._closed.is_set():
            raise BrokerClosed("not connected")
        with self._cmd_lock:
            try:
                self._wfile.write(frame)
                self._wfile.flush()
            except OSError as exc:
                self._closed.set()
                raise BrokerClosed("connection lost: %s" % exc)
            try:
                kind, value = self._responses.get(timeout=self.timeout)
            except queue.Empty:
                raise BrokerError("timed out waiting for server response")
        if kind == "err":
            raise BrokerError(value)
        if kind == "bye":
            raise BrokerClosed(value or "server closed the connection")
        return kind, value

    # -- public API --------------------------------------------------------

    def publish(self, topic: str, payload) -> int:
        """Publish *payload* (bytes or str) to *topic*.  Returns the global
        sequence number assigned by the broker."""
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        _, text = self._roundtrip(encode_publish(topic, bytes(payload)))
        try:
            return int(text)
        except (TypeError, ValueError):
            return -1

    def subscribe(self, pattern: str) -> None:
        self._roundtrip(encode_simple("SUBSCRIBE", pattern))

    def unsubscribe(self, pattern: str) -> None:
        self._roundtrip(encode_simple("UNSUBSCRIBE", pattern))

    def ping(self) -> bool:
        kind, _ = self._roundtrip(encode_simple("PING"))
        return kind == "pong"

    def stats(self) -> dict:
        kind, value = self._roundtrip(encode_simple("STATS"))
        return value

    def flush(self) -> None:
        self._roundtrip(encode_simple("FLUSH"))

    def shutdown(self) -> None:
        """Ask the server to shut down gracefully."""
        try:
            self._roundtrip(encode_simple("SHUTDOWN"))
        except BrokerClosed:
            pass

    def next_message(self, timeout: float | None = None) -> Message | None:
        """Block until the next pushed message arrives.

        Returns ``None`` on timeout, raises :class:`BrokerClosed` when the
        connection is closed (e.g. after a server SHUTDOWN).
        """
        try:
            item = self._messages.get(timeout=timeout)
        except queue.Empty:
            return None
        if item is _CLOSED:
            raise BrokerClosed("connection to broker closed")
        return item
