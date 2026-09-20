"""Python client SDK for linebus."""

from __future__ import annotations

import queue
import socket
import threading
from dataclasses import dataclass
from typing import Optional

from .protocol import (
    DEFAULT_MAX_COMMAND_SIZE,
    CommandTooLargeError,
    ProtocolParseError,
    encode_command,
    encode_publish,
)


class LinebusError(Exception):
    """Base class for client and server errors."""


class LinebusConnectionError(LinebusError):
    pass


class LinebusTimeout(LinebusError):
    pass


@dataclass(frozen=True)
class MessageEvent:
    sequence: int
    topic: str
    payload: bytes


class LinebusClient:
    """Thread-safe client.

    A background reader separates asynchronously pushed EVENT frames from
    command replies. Multiple application threads may publish or subscribe;
    calls that need a reply are serialized so each response can be matched to
    exactly one request.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 7379,
        *,
        timeout: float = 5.0,
        max_command_size: int = DEFAULT_MAX_COMMAND_SIZE,
    ):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.max_command_size = max_command_size
        self._socket: Optional[socket.socket] = None
        self._reader: Optional[threading.Thread] = None
        self._events: queue.Queue[MessageEvent] = queue.Queue()
        self._reply: queue.Queue = queue.Queue()
        self._request_lock = threading.Lock()
        self._closed = threading.Event()
        self._bye = False
        self._reset_queues()

    def connect(self) -> "LinebusClient":
        if self._socket is not None:
            return self
        sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        sock.settimeout(None)
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            # AF_UNIX test sockets do not support TCP_NODELAY.
            pass
        return self._attach_socket(sock)

    def _attach_socket(self, sock: socket.socket) -> "LinebusClient":
        """Attach an already-connected stream socket.

        The public API uses :meth:`connect`; this hook also lets the test-suite
        exercise the real network session over ``socketpair`` in environments
        where loopback TCP binding is unavailable.
        """

        self._socket = sock
        self._closed.clear()
        self._reset_queues()
        self._reader = threading.Thread(target=self._read_loop, name=f"linebus-client-{id(self):x}", daemon=True)
        self._reader.start()
        return self

    def __enter__(self) -> "LinebusClient":
        return self.connect()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _reset_queues(self) -> None:
        self._events = queue.Queue()
        self._reply = queue.Queue()
        self._bye = False

    def _read_loop(self) -> None:
        buffer = bytearray()
        assert self._socket is not None
        try:
            while not self._closed.is_set():
                line = self._read_line(buffer)
                if line is None:
                    break
                if line.startswith(b"EVENT "):
                    event = self._read_event(line, buffer)
                    self._events.put(event)
                else:
                    text = line.decode("utf-8", errors="replace")
                    if text.startswith("BYE"):
                        self._bye = True
                        self._reply.put(LinebusConnectionError(text))
                        self._closed.set()
                        return
                    self._reply.put(text)
        except (LinebusConnectionError, ProtocolParseError, CommandTooLargeError) as exc:
            self._reply.put(exc)
        finally:
            self._closed.set()
            # Unblock next_message/request callers. The BYE path already put
            # a fatal reply, so do not enqueue a second one.
            if not self._bye:
                self._reply.put(LinebusConnectionError("connection closed"))
            self._events.put(None)  # type: ignore[arg-type]

    def _read_line(self, buffer: bytearray) -> Optional[bytes]:
        while True:
            idx = buffer.find(b"\n")
            if idx >= 0:
                line = bytes(buffer[:idx])
                del buffer[: idx + 1]
                return line
            assert self._socket is not None
            try:
                chunk = self._socket.recv(65536)
            except OSError as exc:
                raise LinebusConnectionError(f"receive failed: {exc}") from exc
            if not chunk:
                if buffer:
                    raise ProtocolParseError("connection closed before line terminator")
                return None
            buffer.extend(chunk)

    def _read_exact(self, buffer: bytearray, length: int) -> bytes:
        while len(buffer) < length:
            assert self._socket is not None
            chunk = self._socket.recv(65536)
            if not chunk:
                raise LinebusConnectionError("connection closed while reading payload")
            buffer.extend(chunk)
        payload = bytes(buffer[:length])
        del buffer[:length]
        return payload

    def _read_event(self, header_line: bytes, buffer: bytearray) -> MessageEvent:
        parts = header_line.split(b" ", 2)
        if len(parts) != 3:
            raise ProtocolParseError("invalid EVENT header")
        rest = parts[2]
        last_space = rest.rfind(b" ")
        if last_space < 0:
            raise ProtocolParseError("invalid EVENT header")
        try:
            sequence = int(parts[1])
            length = int(rest[last_space + 1 :])
        except ValueError as exc:
            raise ProtocolParseError("invalid EVENT header numbers") from exc
        if sequence < 1 or length < 0 or length > self.max_command_size:
            raise ProtocolParseError("invalid EVENT payload bounds")
        topic = rest[:last_space].decode("utf-8", errors="strict")
        payload = self._read_exact(buffer, length)
        terminator = self._read_exact(buffer, 1)
        if terminator != b"\n":
            raise ProtocolParseError("EVENT payload must end with LF")
        return MessageEvent(sequence, topic, payload)

    def _request(self, frame: bytes, timeout: Optional[float] = None) -> str:
        deadline_timeout = self.timeout if timeout is None else timeout
        with self._request_lock:
            self._ensure_open()
            # Drain stale fatal connection sentinel before a new logical request.
            try:
                stale = self._reply.get_nowait()
                if not isinstance(stale, LinebusConnectionError):
                    # Should never happen because requests are serialized.
                    raise LinebusError(f"unexpected stale reply: {stale!r}")
            except queue.Empty:
                pass
            try:
                assert self._socket is not None
                self._socket.sendall(frame)
            except OSError as exc:
                self._closed.set()
                raise LinebusConnectionError(f"send failed: {exc}") from exc
            item = self._reply.get(timeout=deadline_timeout)
            if isinstance(item, Exception):
                raise item
            text = item.decode("utf-8", errors="replace") if isinstance(item, bytes) else item
            if text == "BYE" or text.startswith("BYE "):
                self._bye = True
                self._closed.set()
                raise LinebusConnectionError(text)
            if text == "OK" or text.startswith("OK "):
                return text
            if text.startswith("ERR"):
                raise LinebusError(text)
            raise LinebusError(f"unexpected reply: {text}")

    def ping(self) -> str:
        return self._request(encode_command("PING"))

    def publish(self, topic: str, payload: bytes | str | bytearray | memoryview | None = None) -> int:
        reply = self._request(encode_publish(topic, payload))
        if reply.startswith("OK SEQ "):
            try:
                return int(reply[7:])
            except ValueError as exc:
                raise LinebusError(f"invalid sequence reply: {reply}") from exc
        return 0

    def subscribe(self, topic: str) -> None:
        self._request(encode_command("SUBSCRIBE", topic))

    def unsubscribe(self, topic: str) -> None:
        self._request(encode_command("UNSUBSCRIBE", topic))

    def stats(self) -> dict:
        import json

        reply = self._request(encode_command("STATS"))
        if not reply.startswith("OK "):
            raise LinebusError(f"invalid stats reply: {reply}")
        return json.loads(reply[3:])

    def flush(self) -> None:
        self._request(encode_command("FLUSH"))

    def shutdown(self, timeout: Optional[float] = 2.0) -> None:
        try:
            self._request(encode_command("SHUTDOWN"), timeout=timeout)
        except LinebusConnectionError:
            pass
        self.close()

    def next_message(self, timeout: Optional[float] = None) -> Optional[MessageEvent]:
        try:
            item = self._events.get(timeout=self.timeout if timeout is None else timeout)
        except queue.Empty as exc:
            raise LinebusTimeout("timed out waiting for event") from exc
        if item is None:
            raise LinebusConnectionError("connection closed")
        return item

    def _ensure_open(self) -> None:
        if self._socket is None or self._closed.is_set():
            raise LinebusConnectionError("client is not connected")

    def close(self) -> None:
        self._closed.set()
        sock = self._socket
        self._socket = None
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()
        if self._reader is not None:
            self._reader.join(1.0)
            self._reader = None
