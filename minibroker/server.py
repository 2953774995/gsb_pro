"""TCP network layer for the broker.

Threading model:

* one accept thread;
* per connection, one reader thread (parses commands) and one writer thread
  (drains the connection's ordered outbox onto the socket).

Every reply *and* every pushed message goes through the same per-connection
outbox, so the client sees subscription acks, history replay, live messages
and errors in exactly the order the broker produced them.
"""

from __future__ import annotations

import socket
import threading
from typing import Optional

from .broker import Broker, ClientConnection, _SHUTDOWN_SENTINEL
from .errors import ProtocolError
from .protocol import CommandReader, error as error_frame


class BrokerServer:
    def __init__(
        self,
        broker: Optional[Broker] = None,
        host: str = "127.0.0.1",
        port: int = 7379,
        **broker_kwargs,
    ) -> None:
        self.broker = broker or Broker(**broker_kwargs)
        self.host = host
        self.port = port
        self._sock: Optional[socket.socket] = None
        self._accept_thread: Optional[threading.Thread] = None
        self._threads = []
        self._threads_lock = threading.Lock()

    # ------------------------------------------------------------------ #
    def start(self) -> int:
        self.start_broker()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.host, self.port))
        sock.listen(128)
        sock.settimeout(0.5)
        self._sock = sock
        self.host, self.port = sock.getsockname()[:2]
        self._accept_thread = threading.Thread(
            target=self._accept_loop, name="mb-accept", daemon=True
        )
        self._accept_thread.start()
        return self.port

    def start_broker(self) -> None:
        """Open the AOF without binding a listening socket.

        Useful in combination with :meth:`run_connection` when no TCP port is
        available (tests / embedded usage).
        """
        self.broker.start()

    def run_connection(self, sock: socket.socket, peer: str = "pair") -> ClientConnection:
        """Attach an externally accepted/paired socket as a client connection."""
        conn = self.broker.add_connection(peer=peer)
        reader = threading.Thread(
            target=self._reader_loop, args=(sock, conn),
            name="mb-read-%d" % conn.id, daemon=True,
        )
        writer = threading.Thread(
            target=self._writer_loop, args=(sock, conn),
            name="mb-write-%d" % conn.id, daemon=True,
        )
        with self._threads_lock:
            self._threads.extend([reader, writer])
        reader.start()
        writer.start()
        return conn

    def serve_forever(self) -> None:
        self.start()
        try:
            self.broker.shutdown_event.wait()
        except KeyboardInterrupt:
            self.broker.shutdown()
        self.stop()

    def stop(self, timeout: float = 5.0) -> None:
        event_was_set = self.broker.shutdown_event.is_set()
        if not event_was_set:
            self.broker.shutdown()
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        if self._accept_thread is not None:
            self._accept_thread.join(timeout=timeout)
        with self._threads_lock:
            threads = list(self._threads)
        for thread in threads:
            thread.join(timeout=timeout)
        self.broker.close()

    # ------------------------------------------------------------------ #
    def _accept_loop(self) -> None:
        while not self.broker.shutdown_event.is_set():
            try:
                assert self._sock is not None
                client_sock, addr = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            self._spawn_connection(client_sock, addr)

    def _spawn_connection(self, sock: socket.socket, addr) -> None:
        peer = "%s:%d" % addr[:2]
        conn = self.broker.add_connection(peer=peer)
        reader = threading.Thread(
            target=self._reader_loop,
            args=(sock, conn),
            name="mb-read-%d" % conn.id,
            daemon=True,
        )
        writer = threading.Thread(
            target=self._writer_loop,
            args=(sock, conn),
            name="mb-write-%d" % conn.id,
            daemon=True,
        )
        with self._threads_lock:
            self._threads.extend([reader, writer])
        reader.start()
        writer.start()

    # ------------------------------------------------------------------ #
    def _reader_loop(self, sock: socket.socket, conn: ClientConnection) -> None:
        try:
            stream = sock.makefile("rb")
            reader = CommandReader(stream, self.broker.max_command_size)
            while not self.broker.shutdown_event.is_set():
                try:
                    cmd = reader.read_command()
                except ProtocolError as exc:
                    self._safe_send(conn, error_frame(str(exc)))
                    # A line-aligned error (bad command / oversized line) is
                    # recoverable; truncated/unknown frames are not.
                    msg = str(exc)
                    if "mid-" in msg or msg.startswith("payload too large"):
                        break
                    continue
                if cmd is None:
                    break

                try:
                    if cmd.name == "PUBLISH":
                        try:
                            reader.read_payload(cmd)
                        except ProtocolError as exc:
                            self._safe_send(conn, error_frame(str(exc)))
                            break
                        reply = self.broker.handle_publish(
                            conn, cmd.args[0], cmd.payload
                        )
                    elif cmd.name == "SUBSCRIBE":
                        reply = self.broker.handle_subscribe(conn, cmd.args[0])
                    elif cmd.name == "UNSUBSCRIBE":
                        reply = self.broker.handle_unsubscribe(conn, cmd.args[0])
                    elif cmd.name == "PING":
                        reply = self.broker.handle_ping(conn)
                    elif cmd.name == "STATS":
                        reply = self.broker.handle_stats(conn)
                    elif cmd.name == "FLUSH":
                        reply = self.broker.handle_flush(conn)
                    elif cmd.name == "SHUTDOWN":
                        self._safe_send(
                            conn,
                            b"+BYE shutdown requested by " +
                            conn.peer.encode("utf-8", errors="replace") + b"\n",
                        )
                        threading.Thread(
                            target=self.broker.shutdown, daemon=True
                        ).start()
                        break
                    else:  # pragma: no cover - parser guarantees membership
                        reply = error_frame("unknown command")
                    self._safe_send(conn, reply)
                except ProtocolError as exc:
                    # Topic validation errors from the core, etc.
                    self._safe_send(conn, error_frame(str(exc)))
                    continue
                except Exception as exc:  # never let one command kill the thread
                    self._safe_send(
                        conn, error_frame("internal error: %s" % exc)
                    )
        except (OSError, ConnectionError):
            pass
        finally:
            self.broker.remove_connection(conn)
            try:
                sock.shutdown(socket.SHUT_RD)
            except OSError:
                pass

    def _writer_loop(self, sock: socket.socket, conn: ClientConnection) -> None:
        try:
            while True:
                batch = self.broker.drain_outbox(conn)
                if batch is None:
                    return  # connection removed
                shutting = False
                try:
                    for frame in batch:
                        if frame is _SHUTDOWN_SENTINEL:
                            shutting = True
                            break
                        sock.sendall(frame)
                except OSError:
                    return
                self.broker.on_batch_sent(conn)
                if shutting:
                    try:
                        sock.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                    return
        finally:
            try:
                sock.close()
            except OSError:
                pass
            self.broker.remove_connection(conn)

    # ------------------------------------------------------------------ #
    def _safe_send(self, conn: ClientConnection, frame: bytes) -> None:
        """Enqueue a reply, unless the connection is already torn down."""
        with self.broker.lock:
            if conn.closed:
                return
            conn.outbox.append(frame)
            self.broker._cv.notify_all()
