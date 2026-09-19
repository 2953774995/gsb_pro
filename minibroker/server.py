"""TCP server: one reader thread plus one writer thread per connection.

The reader thread parses commands and mutates broker state; all outbound
bytes (command responses, asynchronously pushed MSG frames, BYE
notifications) flow through the connection's bounded mailbox and are
written by the writer thread, so socket writes are never concurrent.
"""

from __future__ import annotations

import argparse
import itertools
import json
import queue
import signal
import socket
import threading
import time

from . import protocol
from .broker import Broker, Mailbox, QueueFull
from .protocol import (
    DEFAULT_MAX_COMMAND_SIZE,
    ProtocolError,
    encode_err,
    encode_msg,
    encode_ok,
    encode_stats,
    read_exact,
    read_line,
)

_GRACEFUL_DRAIN_SECONDS = 0.3

# Outbound-queue sentinel: flush everything queued so far, then close.
_CLOSE_WHEN_FLUSHED = object()


class ClientConnection:
    """Server-side state for one connected client."""

    _ids = itertools.count(1)

    def __init__(self, server: "BrokerServer", sock: socket.socket, addr):
        self.id = next(self._ids)
        self.server = server
        self.addr = addr
        self._sock = sock
        self._rfile = sock.makefile("rb")
        self._wfile = sock.makefile("wb")
        self._alive = True
        self._close_lock = threading.Lock()
        self.mailbox = Mailbox(server.max_pending, is_alive=lambda: self._alive)
        self._writer = threading.Thread(
            target=self._writer_loop, name="mb-writer-%d" % self.id, daemon=True
        )
        self._reader = threading.Thread(
            target=self._reader_loop, name="mb-reader-%d" % self.id, daemon=True
        )

    # -- lifecycle -------------------------------------------------------

    def start(self) -> None:
        self._writer.start()
        self._reader.start()

    def is_alive(self) -> bool:
        return self._alive

    def close(self) -> None:
        with self._close_lock:
            if not self._alive:
                return
            self._alive = False
        self.server.broker.connection_closed(self.id)
        self.server._unregister(self)
        # Shutdown before closing the makefile objects so the reader
        # thread blocked in read() wakes up (avoids a buffer-lock deadlock).
        try:
            self._sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        for closeable in (self._rfile, self._wfile):
            try:
                closeable.close()
            except OSError:
                pass
        try:
            self._sock.close()
        except OSError:
            pass

    # -- outbound --------------------------------------------------------

    def respond(self, data: bytes) -> None:
        try:
            self.mailbox.put_response(data)
        except queue.Full:
            # Client is not draining and its mailbox is full of messages:
            # there is no way to talk to it any more.
            self.close()

    def respond_error(self, message: str) -> None:
        self.respond(encode_err(message))

    def _close_after_flush(self) -> None:
        """Close the connection once everything queued so far is written."""
        try:
            self.mailbox.put_response(_CLOSE_WHEN_FLUSHED)
        except queue.Full:
            self.close()

    def notify(self, data: bytes) -> None:
        """Best-effort notification (BYE) used during shutdown."""
        try:
            self.mailbox.put_response(data)
        except queue.Full:
            pass

    def _writer_loop(self) -> None:
        while True:
            try:
                item = self.mailbox.queue.get(timeout=0.1)
            except queue.Empty:
                if not self._alive:
                    return
                continue
            if item is _CLOSE_WHEN_FLUSHED:
                self.close()
                return
            try:
                if isinstance(item, bytes):
                    self._wfile.write(item)
                else:
                    seq, topic, payload = item
                    self._wfile.write(encode_msg(seq, topic, payload))
                self._wfile.flush()
            except OSError:
                self.close()
                return

    # -- inbound ---------------------------------------------------------

    def _reader_loop(self) -> None:
        graceful = False
        try:
            while self._alive and not self.server.is_shutting_down:
                try:
                    line = read_line(self._rfile, self.server.max_command_size)
                except ProtocolError as exc:
                    self.respond_error(str(exc))
                    continue
                if not line.strip():
                    self.respond_error("empty command")
                    continue
                if not self._dispatch(line):
                    graceful = True
                    break
        except (EOFError, OSError):
            pass
        finally:
            if graceful:
                # Let the writer flush the queued error frame, then close.
                self._close_after_flush()
            else:
                self.close()

    def _dispatch(self, line: bytes) -> bool:
        """Handle one command line.  Returns False when the connection
        should be closed."""
        parts = line.split(b" ")
        cmd = parts[0].upper()
        handler = _COMMAND_HANDLERS.get(cmd)
        if handler is None:
            self.respond_error("unknown command %r" % _safe(parts[0]))
            return True
        try:
            return handler(self, parts)
        except ValueError as exc:
            self.respond_error(str(exc))
            return True

    # -- command handlers ------------------------------------------------

    def _cmd_publish(self, parts) -> bool:
        if len(parts) != 3:
            self.respond_error("malformed PUBLISH: expected PUBLISH <topic> <length>")
            return True
        try:
            topic = parts[1].decode("utf-8")
        except UnicodeDecodeError:
            self.respond_error("invalid topic: not valid UTF-8")
            return True
        try:
            length = int(parts[2])
        except ValueError:
            self.respond_error("invalid payload length %r" % _safe(parts[2]))
            return True
        if length < 0:
            self.respond_error("invalid payload length: must be >= 0")
            return True
        if length > self.server.max_command_size:
            # We cannot safely resynchronise without reading an unbounded
            # amount of data: report the error and drop the connection.
            self.respond_error("command too large")
            return False
        payload = read_exact(self._rfile, length)  # EOFError -> close
        try:
            seq = self.server.broker.publish(topic, payload)
        except QueueFull as exc:
            self.respond_error(str(exc))
            return True
        self.respond(encode_ok(str(seq)))
        return True

    def _cmd_subscribe(self, parts) -> bool:
        if len(parts) != 2:
            self.respond_error("malformed SUBSCRIBE: expected SUBSCRIBE <pattern>")
            return True
        pattern = _decode_token(parts[1])
        self.server.broker.subscribe(self.id, pattern, self.mailbox)
        self.respond(encode_ok("subscribed " + pattern))
        return True

    def _cmd_unsubscribe(self, parts) -> bool:
        if len(parts) != 2:
            self.respond_error("malformed UNSUBSCRIBE: expected UNSUBSCRIBE <pattern>")
            return True
        pattern = _decode_token(parts[1])
        removed = self.server.broker.unsubscribe(self.id, pattern)
        self.respond(encode_ok("unsubscribed " + pattern if removed else "not subscribed"))
        return True

    def _cmd_ping(self, parts) -> bool:
        self.respond(b"PONG\n")
        return True

    def _cmd_stats(self, parts) -> bool:
        stats = self.server.broker.stats()
        stats["connections"] = self.server.connection_count
        stats["max_command_size"] = self.server.max_command_size
        self.respond(encode_stats(json.dumps(stats).encode("utf-8")))
        return True

    def _cmd_flush(self, parts) -> bool:
        self.server.broker.flush()
        self.respond(encode_ok("flushed"))
        return True

    def _cmd_shutdown(self, parts) -> bool:
        self.respond(encode_ok("shutting down"))
        threading.Thread(target=self.server.stop, name="mb-shutdown", daemon=True).start()
        return True


_COMMAND_HANDLERS = {
    b"PUBLISH": ClientConnection._cmd_publish,
    b"SUBSCRIBE": ClientConnection._cmd_subscribe,
    b"UNSUBSCRIBE": ClientConnection._cmd_unsubscribe,
    b"PING": ClientConnection._cmd_ping,
    b"STATS": ClientConnection._cmd_stats,
    b"FLUSH": ClientConnection._cmd_flush,
    b"SHUTDOWN": ClientConnection._cmd_shutdown,
}


def _safe(token: bytes) -> str:
    return token.decode("utf-8", "replace")


def _decode_token(token: bytes) -> str:
    try:
        return token.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("invalid topic: not valid UTF-8")


class BrokerServer:
    """A multithreaded TCP pub/sub broker."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 7379,
        *,
        retention: int = 1000,
        max_pending: int = 10000,
        on_full: str = "error",
        aof_path: str | None = ".broker.aof",
        aof_fsync: bool = False,
        max_command_size: int = DEFAULT_MAX_COMMAND_SIZE,
    ):
        self.host = host
        self.port = port
        self.max_pending = max_pending
        self.max_command_size = max_command_size
        self.broker = Broker(
            retention=retention, on_full=on_full, aof_path=aof_path, aof_fsync=aof_fsync
        )
        self._sock = None
        self._accept_thread = None
        self._shutdown = threading.Event()
        self._connections = set()
        self._conn_lock = threading.Lock()

    # -- lifecycle -------------------------------------------------------

    @property
    def is_shutting_down(self) -> bool:
        return self._shutdown.is_set()

    @property
    def connection_count(self) -> int:
        with self._conn_lock:
            return len(self._connections)

    def start(self) -> None:
        """Bind, listen and spawn the accept thread (non-blocking)."""
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((self.host, self.port))
        self._sock.listen(128)
        self._sock.settimeout(0.2)
        self.host, self.port = self._sock.getsockname()[:2]
        self._accept_thread = threading.Thread(
            target=self._accept_loop, name="mb-accept", daemon=True
        )
        self._accept_thread.start()

    def serve_forever(self) -> None:
        """Block until :meth:`stop` is called (e.g. via SHUTDOWN or signal)."""
        while not self._shutdown.is_set():
            time.sleep(0.1)

    def stop(self) -> None:
        """Gracefully shut down: notify clients with BYE, let the frames
        drain, then close everything."""
        if self._shutdown.is_set():
            return
        with self._conn_lock:
            conns = list(self._connections)
        for conn in conns:
            conn.notify(b"BYE server shutting down\n")
        time.sleep(_GRACEFUL_DRAIN_SECONDS)
        self._shutdown.set()
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        for conn in conns:
            conn.close()
        self.broker.close()
        if self._accept_thread is not None:
            self._accept_thread.join(timeout=2)

    # -- accept loop -----------------------------------------------------

    def _accept_loop(self) -> None:
        while not self._shutdown.is_set():
            try:
                sock, addr = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            self._handle_accepted(sock, addr)

    def _handle_accepted(self, sock: socket.socket, addr) -> ClientConnection:
        """Register and serve an already-connected socket."""
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass  # not a TCP socket (e.g. socketpair in tests)
        conn = ClientConnection(self, sock, addr)
        with self._conn_lock:
            self._connections.add(conn)
        conn.start()
        return conn

    def _unregister(self, conn: ClientConnection) -> None:
        with self._conn_lock:
            self._connections.discard(conn)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="minibroker", description="minibroker pub/sub message broker"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7379)
    parser.add_argument(
        "--retention",
        type=int,
        default=1000,
        help="messages retained per topic for late subscribers (0 = discard)",
    )
    parser.add_argument(
        "--max-pending",
        type=int,
        default=10000,
        help="max undelivered messages buffered per subscriber connection",
    )
    parser.add_argument(
        "--on-full",
        choices=("error", "block"),
        default="error",
        help="PUBLISH behaviour when a subscriber queue is full",
    )
    parser.add_argument("--aof", default=".broker.aof", help="AOF file path")
    parser.add_argument("--no-aof", action="store_true", help="disable persistence")
    parser.add_argument("--aof-fsync", action="store_true", help="fsync every append")
    parser.add_argument(
        "--max-command-size",
        type=int,
        default=DEFAULT_MAX_COMMAND_SIZE,
        help="max size of a single command in bytes",
    )
    args = parser.parse_args(argv)

    server = BrokerServer(
        host=args.host,
        port=args.port,
        retention=args.retention,
        max_pending=args.max_pending,
        on_full=args.on_full,
        aof_path=None if args.no_aof else args.aof,
        aof_fsync=args.aof_fsync,
        max_command_size=args.max_command_size,
    )
    server.start()

    def _handle_signal(signum, frame):
        server.stop()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    print(
        "minibroker listening on %s:%d (retention=%d, on_full=%s, aof=%s)"
        % (
            server.host,
            server.port,
            args.retention,
            args.on_full,
            "disabled" if args.no_aof else args.aof,
        ),
        flush=True,
    )
    server.serve_forever()
    print("minibroker stopped", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
