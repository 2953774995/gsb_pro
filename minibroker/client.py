"""Python client SDK for minibroker.

A single background reader thread parses server frames. Command replies are
delivered to the calling thread through a one-shot condition; pushed ``MSG``
frames land in a per-client queue consumed by :meth:`BrokerClient.next_message`
(and optionally forwarded to an ``on_message`` callback).
"""

from __future__ import annotations

import socket
import threading
import time
from collections import deque
from typing import Callable, Deque, Optional, Tuple

from .errors import BrokerShutdown, ProtocolError, ServerError
from .protocol import (
    DEFAULT_PORT,
    ReplyReader,
    encode_command,
    validate_subscription_topic,
    validate_topic,
)

Message = Tuple[str, int, bytes]
MessageCallback = Callable[[str, int, bytes], None]


class BrokerClient:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = DEFAULT_PORT,
        timeout: float = 10.0,
        on_message: Optional[MessageCallback] = None,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.on_message = on_message

        self._sock: Optional[socket.socket] = None
        self._reader: Optional[threading.Thread] = None
        self._write_lock = threading.Lock()

        self._lock = threading.Condition()
        self._reply: Optional[tuple] = None
        self._messages: Deque[Message] = deque()
        self._closed = False
        self._server_shutdown = False

    # ------------------------------------------------------------------ #
    # connection management
    # ------------------------------------------------------------------ #
    def connect(self) -> "BrokerClient":
        sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        return self.adopt_socket(sock)

    def adopt_socket(self, sock: socket.socket) -> "BrokerClient":
        """Start the reader loop on an already established socket.

        Mostly useful for tests that connect over a pre-arranged socket pair;
        production code uses :meth:`connect`.
        """
        sock.settimeout(None)
        self._sock = sock
        self._reader = threading.Thread(
            target=self._read_loop,
            name="mb-client-reader",
            daemon=True,
        )
        self._reader.start()
        return self

    def __enter__(self) -> "BrokerClient":
        if self._sock is None:
            self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            sock, self._sock = self._sock, None
            self._lock.notify_all()
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass
        if self._reader is not None and threading.current_thread() is not self._reader:
            self._reader.join(timeout=1.0)

    @property
    def closed(self) -> bool:
        return self._closed

    # ------------------------------------------------------------------ #
    # commands
    # ------------------------------------------------------------------ #
    def ping(self) -> bool:
        reply = self._request(encode_command("PING"))
        return reply[0] == "PONG"

    def publish(self, topic: str, payload: bytes | bytearray | memoryview | str = b"") -> int:
        validate_topic(topic)
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        reply = self._request(encode_command("PUBLISH", topic, payload=bytes(payload)))
        return int(reply[1])

    def subscribe(self, topic: str) -> None:
        validate_subscription_topic(topic)
        self._request(encode_command("SUBSCRIBE", topic))

    def unsubscribe(self, topic: str) -> None:
        validate_subscription_topic(topic)
        self._request(encode_command("UNSUBSCRIBE", topic))

    def stats(self) -> dict:
        reply = self._request(encode_command("STATS"))
        return reply[1]

    def flush(self) -> None:
        self._request(encode_command("FLUSH"))

    def shutdown(self) -> None:
        """Ask the broker to shut down. The connection always ends closed."""
        try:
            self._request(encode_command("SHUTDOWN"))
        except BrokerShutdown:
            pass
        finally:
            self.close()

    # ------------------------------------------------------------------ #
    # pushed messages
    # ------------------------------------------------------------------ #
    def next_message(self, timeout: Optional[float] = None) -> Optional[Message]:
        """Block until a pushed message is available.

        Returns ``(topic, seq, payload)`` or ``None`` on timeout. Raises
        :class:`BrokerShutdown` if the broker went away via SHUTDOWN (after
        any queued messages have been drained).
        """
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._lock:
            while not self._messages:
                if self._server_shutdown:
                    raise BrokerShutdown("broker shut down")
                if self._closed:
                    raise ProtocolError("connection closed")
                if deadline is None:
                    self._lock.wait()
                else:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return None
                    self._lock.wait(timeout=remaining)
            return self._messages.popleft()

    # ------------------------------------------------------------------ #
    # internals
    # ------------------------------------------------------------------ #
    def _request(self, frame: bytes, timeout: Optional[float] = None) -> tuple:
        if self._closed:
            raise ProtocolError("client is closed")
        with self._lock:
            self._reply = None
        if self._sock is None:
            raise ProtocolError("not connected")
        with self._write_lock:
            if self._sock is None:
                raise ProtocolError("not connected")
            self._sock.sendall(frame)

        deadline = time.monotonic() + (timeout if timeout is not None else self.timeout)
        with self._lock:
            while self._reply is None:
                if self._server_shutdown:
                    raise BrokerShutdown("broker shut down")
                if self._closed:
                    raise ProtocolError("connection closed before reply")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ProtocolError("request timed out")
                self._lock.wait(timeout=remaining)
            reply = self._reply
            self._reply = None

        kind = reply[0]
        if kind == "ERR":
            raise ServerError(reply[1])
        if kind == "BYE":
            raise BrokerShutdown(reply[1])
        return reply

    def _read_loop(self) -> None:
        sock = self._sock
        try:
            assert sock is not None
            stream = sock.makefile("rb")
            reader = ReplyReader(stream)
            while True:
                reply = reader.read_reply()
                kind = reply[0]
                if kind == "MSG":
                    _, topic, seq, payload = reply
                    msg = (topic, seq, payload)
                    with self._lock:
                        self._messages.append(msg)
                        self._lock.notify_all()
                    if self.on_message is not None:
                        try:
                            self.on_message(topic, seq, payload)
                        except Exception:  # pragma: no cover - user callback
                            pass
                else:
                    if kind == "BYE":
                        with self._lock:
                            self._server_shutdown = True
                            self._reply = reply
                            self._lock.notify_all()
                        return
                    with self._lock:
                        self._reply = reply
                        self._lock.notify_all()
        except (ProtocolError, OSError, ValueError):
            pass
        finally:
            with self._lock:
                if not self._server_shutdown:
                    self._reply = ("ERR", "connection closed by server")
                self._closed = True
                self._lock.notify_all()
            try:
                if sock is not None:
                    sock.close()
            except OSError:
                pass
