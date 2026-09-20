"""Synchronous Python SDK for minibroker.

One background socket-reader thread parses replies.  Positive command replies
wake the calling thread, while asynchronous ``PUB`` frames enter a message
queue and can be consumed with :meth:`BrokerClient.next_message`.
"""

from __future__ import annotations

import socket
import threading
import time
from dataclasses import dataclass
from queue import Empty, Queue
from typing import Any, Callable, Optional

from . import protocol


class ClientError(Exception):
    """Base error for local client/protocol failures."""


class ServerError(ClientError):
    """Raised when the server returns an ``-ERR ...`` reply."""


@dataclass(frozen=True)
class Message:
    sequence: int
    topic: bytes
    payload: bytes


class BrokerClient:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 7379,
        *,
        timeout: Optional[float] = None,
        on_event: Optional[Callable[[str], None]] = None,
    ):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.on_event = on_event

        self._socket: Optional[socket.socket] = None
        self._reader_file = None
        self._reader_gone = threading.Event()
        self._reader_thread: Optional[threading.Thread] = None
        self._closed = False
        self._lock = threading.Lock()
        self._request_id = 0
        self._response_events: dict = {}
        self._response_values: dict = {}
        self.messages: "Queue[Message]" = Queue()
        self.server_shutdown = threading.Event()

    # -------------------------------------------------------------- lifecycle
    def connect(self) -> "BrokerClient":
        if self._socket is not None:
            return self
        sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        sock.settimeout(None)
        if sock.family == socket.AF_INET or sock.family == socket.AF_INET6:
            try:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except OSError:
                pass
        self._socket = sock
        self._reader_file = sock.makefile("rb")
        self._reader_thread = threading.Thread(
            target=self._read_loop, name="mb-client-reader", daemon=True
        )
        self._reader_thread.start()
        return self

    def __enter__(self) -> "BrokerClient":
        return self.connect()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _shutdown_write(self) -> None:
        sock = self._socket
        if sock is not None:
            # Half-close first so the server sees EOF.  Keep the socket fd
            # alive briefly; dropping it immediately can race the peer's read
            # on AF_UNIX socketpairs used by tests.
            try:
                sock.shutdown(socket.SHUT_WR)
            except OSError:
                pass

    def _close_socket(self) -> None:
        sock = self._socket
        self._socket = None
        if self._reader_thread is not None and self._reader_thread is not threading.current_thread():
            self._reader_gone.wait(2)
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        if self._reader_file is not None:
            try:
                self._reader_file.close()
            except OSError:
                pass

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        with self._lock:
            pending = list(self._response_events.items())
            self._response_events.clear()
        for request_id, event in pending:
            self._response_values[request_id] = ClientError("client closed")
            event.set()
        self._shutdown_write()

    # ---------------------------------------------------------------- commands
    def _request(self, *parts: Any, timeout: Optional[float] = None) -> Any:
        with self._lock:
            if self._closed or self._socket is None:
                raise ClientError("client is not connected")
            request_id = self._request_id
            self._request_id += 1
            event = threading.Event()
            self._response_events[request_id] = event
            try:
                self._socket.sendall(protocol.encode_command(*parts))
            except OSError as exc:
                self._response_events.pop(request_id, None)
                raise ClientError(f"failed to send command: {exc}") from exc

        deadline = None if timeout is None else time.monotonic() + timeout
        while not event.wait(0.2):
            if self._closed:
                raise ClientError("client closed while waiting for reply")
            if deadline is not None and time.monotonic() >= deadline:
                self._response_events.pop(request_id, None)
                raise TimeoutError("timed out waiting for server reply")

        self._response_events.pop(request_id, None)
        value = self._response_values.pop(request_id, None)
        if isinstance(value, Exception):
            raise value
        return value

    def ping(self) -> bytes:
        value = self._request("PING")
        return self._expect_simple(value, b"PONG")

    def publish(self, topic, payload: bytes) -> int:
        topic = self._to_bytes(topic)
        payload = self._to_bytes(payload)
        value = self._request("PUBLISH", topic, payload)
        if not isinstance(value, int):
            raise ClientError("expected integer PUBLISH response")
        return value

    def subscribe(self, topic) -> None:
        value = self._request("SUBSCRIBE", self._to_bytes(topic))
        self._expect_simple(value, b"SUBSCRIBED")

    def unsubscribe(self, topic) -> bool:
        value = self._request("UNSUBSCRIBE", self._to_bytes(topic))
        if value == b"UNSUBSCRIBED":
            return True
        if value == b"NOT_SUBSCRIBED":
            return False
        raise ClientError("unexpected UNSUBSCRIBE response")

    def stats(self) -> dict:
        value = self._request("STATS")
        if (
            not isinstance(value, list)
            or not value
            or value[0] != b"STATS"
            or (len(value) - 1) % 2
        ):
            raise ClientError("invalid STATS response")
        result = {}
        integer_fields = {
            "connections",
            "max_client_queue",
            "next_sequence",
            "pending_messages",
            "published_total",
            "retained_messages",
            "retention_limit",
            "subscriptions",
            "topics",
        }
        for raw_key, raw_val in zip(value[1::2], value[2::2]):
            key = raw_key.decode("utf-8")
            result[key] = int(raw_val) if key in integer_fields else raw_val
        return result

    def flush(self) -> None:
        value = self._request("FLUSH")
        self._expect_simple(value, b"FLUSHED")

    def shutdown(self) -> None:
        try:
            value = self._request("SHUTDOWN", timeout=5)
            self._expect_simple(value, b"BYE")
        except Exception:
            # The server may close just before/while the reply is delivered; the
            # asynchronous SHUTDOWN event is the authoritative confirmation.
            pass
        self.server_shutdown.wait(2)

    # ----------------------------------------------------------------- receive
    def next_message(self, timeout: Optional[float] = None) -> Message:
        try:
            return self.messages.get(block=True, timeout=timeout)
        except Empty as exc:
            raise TimeoutError("timed out waiting for message") from exc

    def event_count(self) -> int:
        return self.messages.qsize()

    # ---------------------------------------------------------------- internal
    @staticmethod
    def _to_bytes(value) -> bytes:
        if isinstance(value, bytes):
            return value
        if isinstance(value, str):
            return value.encode("utf-8")
        raise TypeError("topic and payload must be bytes or str")

    @staticmethod
    def _expect_simple(value, expected: bytes) -> Any:
        if value != expected:
            if isinstance(value, bytes):
                raise ClientError(f"unexpected reply: {value!r}")
            raise ClientError("unexpected reply type")
        return value

    def _read_loop(self) -> None:
        assert self._reader_file is not None
        try:
            while not self._closed:
                value = protocol.read_value(self._reader_file, protocol.DEFAULT_MAX_FRAME_SIZE)
                if isinstance(value, list) and value and value[0] == b"PUB":
                    if len(value) != 4:
                        raise ClientError("invalid PUB frame")
                    sequence = int(value[1])
                    self.messages.put(Message(sequence, value[2], value[3]))
                elif isinstance(value, list) and value and value[0] == b"SHUTDOWN":
                    self.server_shutdown.set()
                    if self.on_event is not None:
                        self.on_event("shutdown")
                else:
                    self._dispatch_response(value)
        except (EOFError, OSError, protocol.ProtocolError, ClientError, ValueError):
            self.server_shutdown.set()
            self._fail_all(ClientError("server connection closed"))
        finally:
            self._reader_gone.set()
            if self._closed:
                self._close_socket()

    def _dispatch_response(self, value: Any) -> None:
        # Direct replies arrive in request order over this TCP connection.
        with self._lock:
            request_id = min(self._response_events) if self._response_events else None
            event = self._response_events.pop(request_id, None) if request_id is not None else None

        reply = value
        if isinstance(value, bytes) and value.startswith(b"ERR "):
            reply = ServerError(value[4:].decode("utf-8", "replace"))
        if event is None or request_id is None:
            return
        self._response_values[request_id] = reply
        event.set()

    def _fail_all(self, error: Exception) -> None:
        with self._lock:
            pending = list(self._response_events.items())
            self._response_events.clear()
        for request_id, event in pending:
            self._response_values[request_id] = error
            event.set()
        self._closed = True
