"""Python client SDK for Linebus."""

from __future__ import annotations

import queue
import socket
import threading
from dataclasses import dataclass
from typing import Optional

from .protocol import (
    DEFAULT_MAX_COMMAND_SIZE,
    Frame,
    ProtocolError,
    CommandTooLargeError,
    encode_publish,
    encode_simple,
    encode_subscribe,
    encode_unsubscribe,
    parse_event_frame,
    read_frame,
    validate_topic,
)


class LinebusError(Exception):
    """Base client error."""


class LinebusProtocolError(LinebusError):
    """The server returned data that the client cannot interpret."""


class LinebusServerError(LinebusError):
    """The server returned an ``ERR`` response."""


class LinebusDisconnected(LinebusError):
    """The client is not connected or the server closed the socket."""


@dataclass(frozen=True)
class Message:
    sequence: int
    topic: str
    payload: bytes


class LinebusClient:
    """Synchronous Linebus client.

    A background receiver thread routes command responses and asynchronous
    events to independent queues. ``next_message`` therefore works while the
    client is in subscription mode.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 7379,
        *,
        timeout: Optional[float] = None,
        connect_timeout: Optional[float] = 10.0,
        max_command_size: int = DEFAULT_MAX_COMMAND_SIZE,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.connect_timeout = connect_timeout
        self.max_command_size = max_command_size
        self._sock: Optional[socket.socket] = None
        self._stream = None
        self._reader_thread: Optional[threading.Thread] = None
        self._response_queue: "queue.Queue[object]" = queue.Queue()
        self._event_queue: "queue.Queue[object]" = queue.Queue()
        self._request_lock = threading.Lock()
        self._closed = False

    def connect(self) -> "LinebusClient":
        if self._sock is not None:
            return self
        sock = socket.create_connection((self.host, self.port), timeout=self.connect_timeout)
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.settimeout(self.timeout)
        self._sock = sock
        self._stream = sock.makefile("rb")
        self._closed = False
        self._reader_thread = threading.Thread(
            target=self._reader_loop, name="linebus-client-reader", daemon=True
        )
        self._reader_thread.start()
        return self

    def attach_socket(self, sock: socket.socket) -> "LinebusClient":
        """Attach an already-connected socket (mainly used by tests)."""
        if self._sock is not None:
            raise LinebusError("client is already connected")
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.settimeout(self.timeout)
        self._sock = sock
        self._stream = sock.makefile("rb")
        self._closed = False
        self._reader_thread = threading.Thread(
            target=self._reader_loop, name="linebus-client-reader", daemon=True
        )
        self._reader_thread.start()
        return self

    def __enter__(self) -> "LinebusClient":
        return self.connect()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    @property
    def connected(self) -> bool:
        return self._sock is not None and not self._closed

    def _reader_loop(self) -> None:
        assert self._stream is not None
        try:
            while not self._closed:
                frame = read_frame(self._stream, self.max_command_size)
                if frame is None:
                    raise LinebusDisconnected("server closed the connection")
                if frame.command == "EVENT":
                    sequence, topic, payload = parse_event_frame(frame)
                    self._event_queue.put(Message(sequence, topic, payload))
                elif frame.command == "ERR":
                    self._response_queue.put(LinebusServerError(" ".join(frame.parts[1:])))
                else:
                    self._response_queue.put(frame)
                    # Unsolicited shutdown notices can arrive while the
                    # application is blocked in next_message(), not waiting for
                    # a command response.
                    if frame.command == "OK" and len(frame.parts) > 1 and frame.parts[1] == "SERVER_SHUTDOWN":
                        self._event_queue.put(LinebusDisconnected("server is shutting down"))
        except (ProtocolError, CommandTooLargeError, LinebusError, OSError, ValueError) as exc:
            self._response_queue.put(
                LinebusDisconnected(str(exc)) if isinstance(exc, OSError) else exc
            )
        finally:
            sentinel = LinebusDisconnected("connection closed")
            # Unblock callers on either queue. Duplicated sentinels are safe.
            self._event_queue.put(sentinel)
            self._response_queue.put(sentinel)

    def _send(self, data: bytes) -> None:
        if self._sock is None or self._closed:
            raise LinebusDisconnected("client is not connected")
        self._sock.sendall(data)

    def _request_ok(self, data: bytes, *, ok_prefix: Optional[str] = None) -> Frame:
        with self._request_lock:
            self._send(data)
            item = self._response_queue.get()
        return self._expect_ok(item, ok_prefix)

    def _expect_ok(self, item: object, ok_prefix: Optional[str]) -> Frame:
        if isinstance(item, Exception):
            raise item
        if not isinstance(item, Frame) or item.command != "OK":
            raise LinebusProtocolError(f"unexpected response: {item!r}")
        if ok_prefix is not None and (len(item.parts) < 2 or item.parts[1] != ok_prefix):
            raise LinebusProtocolError(f"expected OK {ok_prefix}, got: {' '.join(item.parts)}")
        return item

    def ping(self) -> str:
        frame = self._request_ok(encode_simple("PING"))
        return " ".join(frame.parts[1:])

    def publish(self, topic: str, payload: bytes = b"") -> int:
        topic = validate_topic(topic)
        if not isinstance(payload, (bytes, bytearray)):
            raise TypeError("payload must be bytes")
        frame = self._request_ok(encode_publish(topic, bytes(payload)), ok_prefix="PUBLISHED")
        try:
            return int(frame.parts[2])
        except (IndexError, ValueError) as exc:
            raise LinebusProtocolError("invalid PUBLISH response") from exc

    def subscribe(self, topic: str) -> None:
        topic = validate_topic(topic, allow_wildcard=True)
        self._request_ok(encode_subscribe(topic), ok_prefix="SUBSCRIBED")

    def unsubscribe(self, topic: str) -> None:
        topic = validate_topic(topic, allow_wildcard=True)
        self._request_ok(encode_unsubscribe(topic), ok_prefix="UNSUBSCRIBED")

    def stats(self) -> dict:
        frame = self._request_ok(encode_simple("STATS"), ok_prefix="STATS")
        values = {}
        for token in frame.payload.decode("utf-8").split(" "):
            if "=" not in token:
                raise LinebusProtocolError("invalid STATS payload")
            key, value = token.split("=", 1)
            try:
                values[key] = int(value)
            except ValueError as exc:
                raise LinebusProtocolError("invalid STATS value") from exc
        return values

    def flush(self) -> None:
        self._request_ok(encode_simple("FLUSH"), ok_prefix="FLUSHED")

    def shutdown(self) -> None:
        with self._request_lock:
            self._send(encode_simple("SHUTDOWN"))
            item = self._response_queue.get()
        self._expect_ok(item, "SHUTDOWN")

    def next_message(self, timeout: Optional[float] = None) -> Message:
        item = self._event_queue.get(timeout=timeout)
        if isinstance(item, Exception):
            raise item
        if not isinstance(item, Message):
            raise LinebusProtocolError(f"unexpected event: {item!r}")
        return item

    def close(self) -> None:
        self._closed = True
        sock = self._sock
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        if self._stream is not None:
            try:
                self._stream.close()
            except OSError:
                pass
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        self._sock = None
        self._stream = None
        if self._reader_thread is not None and self._reader_thread is not threading.current_thread():
            self._reader_thread.join(timeout=1.0)
