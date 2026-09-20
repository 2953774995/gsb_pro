"""TCP network layer for minibroker.

The server uses one reader thread per connection plus one writer thread per
connection.  Commands are handled on the reader thread, while broker fan-out
only appends to a connection-owned queue.  The writer preserves FIFO order and
keeps a slow/blocked client from blocking publishers or other subscribers.
"""

from __future__ import annotations

import argparse
import socket
import threading
import time
from collections import deque
from typing import Deque, Dict, List, Optional, Tuple

from . import protocol
from .broker import Broker
from .exceptions import BrokerError, PersistenceError, QueueFullError
from .messages import StoredMessage

SHUTDOWN_SENTINEL = object()
QueueItem = object


class Connection:
    def __init__(
        self,
        sock: socket.socket,
        address: Tuple[str, int],
        broker: Broker,
        server: "BrokerServer",
    ):
        self.sock = sock
        self.address = address
        self.broker = broker
        self.server = server
        self.id: int = 0
        self.subscriptions: Dict[bytes, object] = {}

        self._queue: "Deque[object]" = deque()
        self._delivered_sequences: set = set()
        self._queue_lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._wake = threading.Event()
        self.stop_event = threading.Event()
        self._reader: Optional[threading.Thread] = None
        self._writer: Optional[threading.Thread] = None
        self._reader_file = sock.makefile("rb", buffering=0)
        self._closed_once = False

    def start(self) -> None:
        self.broker.register_connection(self)
        self._reader = threading.Thread(
            target=self._run_reader, name=f"mb-reader-{self.id}", daemon=True
        )
        self._writer = threading.Thread(
            target=self._run_writer, name=f"mb-writer-{self.id}", daemon=True
        )
        self._reader.start()
        self._writer.start()

    # Methods called by Broker, normally while holding Broker._lock.
    def enqueue_message(self, subscription_ids: Tuple[int, ...], message: StoredMessage) -> None:
        with self._queue_lock:
            self._queue.append((subscription_ids, message))
        self._wake.set()

    def notify_shutdown(self) -> None:
        # Put the notice behind every already-queued PUB so FIFO order is
        # preserved through the single writer thread.
        with self._queue_lock:
            self._queue.append(SHUTDOWN_SENTINEL)
        self._wake.set()

    def pending_count(self) -> int:
        with self._queue_lock:
            return sum(item is not SHUTDOWN_SENTINEL for item in self._queue)

    def has_seen_sequence(self, sequence: int) -> bool:
        with self._queue_lock:
            return sequence in self._delivered_sequences or any(
                item is not SHUTDOWN_SENTINEL and item[1].sequence == sequence
                for item in self._queue
            )

    def remove_pending_subscription(self, subscription_id: int) -> None:
        with self._queue_lock:
            kept: "Deque[object]" = deque()
            for item in self._queue:
                if item is SHUTDOWN_SENTINEL:
                    kept.append(item)
                    continue
                ids, message = item
                remaining = tuple(item for item in ids if item != subscription_id)
                if remaining:
                    kept.append((remaining, message))
            self._queue = kept

    def clear_pending(self) -> None:
        with self._queue_lock:
            self._queue.clear()
            self._delivered_sequences.clear()

    def _drain_queue(self) -> List[QueueItem]:
        with self._queue_lock:
            items = list(self._queue)
            self._queue.clear()
            self._wake.clear()
        return items

    def _send(self, data: bytes) -> bool:
        try:
            with self._send_lock:
                self.sock.sendall(data)
            return True
        except OSError:
            self.stop_event.set()
            return False

    def _run_writer(self) -> None:
        while not self.stop_event.is_set():
            self._wake.wait(0.2)
            if self.stop_event.is_set():
                break
            items = self._drain_queue()
            if not items:
                continue
            chunks = []
            pub_items = []
            for item in items:
                if item is SHUTDOWN_SENTINEL:
                    chunks.append(protocol.encode_frame([b"SHUTDOWN"]))
                    continue
                _ids, message = item
                pub_items.append(message)
                chunks.append(protocol.encode_pub(message.sequence, message.topic, message.payload))
            with self._queue_lock:
                self._delivered_sequences.update(message.sequence for message in pub_items)
            if not self._send(b"".join(chunks)):
                break

    # -------------------------------------------------------------- commands
    def _run_reader(self) -> None:
        try:
            while not self.stop_event.is_set():
                try:
                    parts = protocol.read_frame(self._reader_file, self.server.max_frame_size)
                except EOFError:
                    break
                except protocol.ProtocolError as exc:
                    # Once a framing/header parse fails, stream position is no
                    # longer known; report it and close this one bad client.
                    # Half-close the write side and briefly drain input so the
                    # peer can actually receive ERR even when it is still
                    # sending the rejected oversized frame.
                    self._protocol_error_close(str(exc))
                    break
                except (ValueError, OSError):
                    # A concurrently closed file/socket during shutdown can
                    # surface ValueError or OSError instead of a clean EOF.
                    break

                if not parts:
                    self._send(protocol.encode_error("empty command"))
                    continue
                try:
                    command = parts[0].decode("ascii").upper()
                except UnicodeDecodeError:
                    self._send(protocol.encode_error("command name must be ASCII"))
                    continue

                keep_open = self._handle_command(command, parts[1:])
                if not keep_open:
                    break
        finally:
            self.close()

    def _protocol_error_close(self, message: str) -> None:
        self._send(protocol.encode_error(f"protocol error: {message}"))
        try:
            self.sock.shutdown(socket.SHUT_WR)
            self.sock.settimeout(0.5)
            while self.sock.recv(65536):
                pass
        except OSError:
            pass
        finally:
            try:
                self.sock.settimeout(None)
            except OSError:
                pass
            self.close()

    def _reply_error(self, message: str) -> None:
        self._send(protocol.encode_error(message))

    def _handle_command(self, command: str, args: List[bytes]) -> bool:
        try:
            if command == "PING":
                if args:
                    self._reply_error("PING takes no arguments")
                else:
                    self._send(protocol.encode_ok("PONG"))

            elif command == "PUBLISH":
                if len(args) != 2:
                    self._reply_error("PUBLISH requires topic and payload")
                else:
                    message = self.broker.publish(args[0], args[1])
                    self._send(protocol.encode_integer(message.sequence))

            elif command == "SUBSCRIBE":
                if len(args) != 1:
                    self._reply_error("SUBSCRIBE requires one topic")
                else:
                    self.broker.subscribe(self, args[0])
                    self._send(protocol.encode_ok("SUBSCRIBED"))

            elif command == "UNSUBSCRIBE":
                if len(args) != 1:
                    self._reply_error("UNSUBSCRIBE requires one topic")
                else:
                    removed = self.broker.unsubscribe(self, args[0])
                    self._send(protocol.encode_ok("UNSUBSCRIBED" if removed else "NOT_SUBSCRIBED"))

            elif command == "STATS":
                if args:
                    self._reply_error("STATS takes no arguments")
                else:
                    stats = self.broker.stats()
                    frame: List[bytes] = [b"STATS"]
                    for key, value in stats.items():
                        frame.append(key.encode("ascii"))
                        frame.append(str(value).encode("ascii"))
                    self._send(protocol.encode_frame(frame))

            elif command == "FLUSH":
                if args:
                    self._reply_error("FLUSH takes no arguments")
                else:
                    self.broker.flush()
                    self._send(protocol.encode_ok("FLUSHED"))

            elif command == "SHUTDOWN":
                if args:
                    self._reply_error("SHUTDOWN takes no arguments")
                else:
                    self._send(protocol.encode_ok("BYE"))
                    self.server.request_shutdown()
                    # Do not close this reader: the graceful shutdown path
                    # queues an asynchronous SHUTDOWN frame and closes every
                    # connection after delivering it.
                    return True

            else:
                self._reply_error(f"unknown command '{command}'")
        except QueueFullError as exc:
            self._reply_error(str(exc))
        except BrokerError as exc:
            self._reply_error(str(exc))
        except PersistenceError as exc:
            self._reply_error(f"persistence failure: {exc}")
        except Exception:  # Defensive: one malformed request must not stop server.
            self.server.log_exception()
            self._reply_error("internal server error")
        return True

    def join(self, timeout: Optional[float] = None) -> None:
        if self._reader is not None:
            self._reader.join(timeout)
        if self._writer is not None:
            self._writer.join(timeout)

    def close(self) -> None:
        if self._closed_once:
            return
        self._closed_once = True
        self.stop_event.set()
        self._wake.set()
        self.server.remove_connection(self)

        try:
            self.broker.unregister_connection(self)
        except Exception:
            self.server.log_exception()

        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self._reader_file.close()
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


class BrokerServer:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 7379,
        *,
        retention: int = 1000,
        max_client_queue: int = 0,
        aof_path: str = ".broker.aof",
        aof_enabled: bool = True,
        max_frame_size: int = protocol.DEFAULT_MAX_FRAME_SIZE,
        broker: Optional[Broker] = None,
    ):
        self.host = host
        self.port = port
        self.retention = retention
        self.max_client_queue = max_client_queue
        self.aof_path = aof_path
        self.aof_enabled = aof_enabled
        self.max_frame_size = max_frame_size
        self.broker = broker or Broker(
            AppendOnlyLog(aof_path, enabled=aof_enabled),
            retention=retention,
            max_client_queue=max_client_queue,
        )

        self._sock: Optional[socket.socket] = None
        self._accept_thread: Optional[threading.Thread] = None
        self._connections: List[Connection] = []
        self._state_lock = threading.Lock()
        self.shutdown_event = threading.Event()
        self.completed_event = threading.Event()
        self._shutdown_thread: Optional[threading.Thread] = None
        self._actual_port: Optional[int] = None
        # Test/embedding hook: accepted pairs can be injected without binding a
        # listening TCP or UNIX socket.  Production code leaves this at None.
        self.injected_accepts: Optional["List[Tuple[socket.socket, tuple]]"] = None

    @property
    def actual_port(self) -> int:
        if self._actual_port is None:
            raise RuntimeError("server is not listening")
        return self._actual_port

    def start(self) -> "BrokerServer":
        with self._state_lock:
            if self._accept_thread is not None:
                return self
            if self.injected_accepts is not None:
                self._actual_port = 0
                self._accept_thread = threading.Thread(
                    target=self._accept_loop, name="mb-injected-accept", daemon=True
                )
                self._accept_thread.start()
                return self

            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((self.host, self.port))
                sock.listen(128)
            except Exception:
                sock.close()
                raise
            self._sock = sock
            self._actual_port = sock.getsockname()[1]
            self._accept_thread = threading.Thread(
                target=self._accept_loop, name="mb-accept", daemon=True
            )
            self._accept_thread.start()
        return self

    def serve_forever(self) -> None:
        self.start()
        self.shutdown_event.wait()
        self.completed_event.wait(10)

    def _accept_loop(self) -> None:
        while not self.shutdown_event.is_set():
            if self.injected_accepts is not None:
                try:
                    client, address = self.injected_accepts.pop(0)
                except IndexError:
                    time.sleep(0.01)
                    continue
            else:
                assert self._sock is not None
                try:
                    client, address = self._sock.accept()
                except OSError:
                    if self.shutdown_event.is_set():
                        break
                    self.log_exception()
                    time.sleep(0.05)
                    continue
                client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

            conn = Connection(client, address, self.broker, self)
            with self._state_lock:
                self._connections.append(conn)
            conn.start()

    def inject_accepted_socket(self, sock: socket.socket, address=("injected", 0)) -> None:
        if self.injected_accepts is None:
            self.injected_accepts = []
        self.injected_accepts.append((sock, address))

    def remove_connection(self, conn: Connection) -> None:
        with self._state_lock:
            try:
                self._connections.remove(conn)
            except ValueError:
                pass

    def request_shutdown(self) -> None:
        with self._state_lock:
            if self._shutdown_thread is not None:
                return
            self.shutdown_event.set()
            self._shutdown_thread = threading.Thread(
                target=self._graceful_shutdown, name="mb-shutdown", daemon=True
            )
            self._shutdown_thread.start()

    def _close_listener(self) -> None:
        with self._state_lock:
            sock = self._sock
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    def _graceful_shutdown(self) -> None:
        self._close_listener()
        # Give the SHUTDOWN command's own positive reply time to reach its
        # wire queue, and wait briefly for already-queued PUB frames to drain.
        time.sleep(0.1)
        with self._state_lock:
            connections = list(self._connections)
        deadline = time.time() + 2.0
        while time.time() < deadline:
            if all(conn.pending_count() == 0 for conn in connections):
                break
            time.sleep(0.02)
        for conn in connections:
            conn.notify_shutdown()
        time.sleep(0.5)
        for conn in connections:
            conn.close()
        for conn in connections:
            conn.join(1.0)
        self.broker.close()
        self.completed_event.set()

    def stop(self) -> None:
        """Stop from local test/control code, using the same graceful path."""

        self.request_shutdown()
        self.completed_event.wait(10)

    def log_exception(self) -> None:
        # A tiny server should be easy to embed in tests; import lazily because
        # traceback formatting is only useful for unexpected exceptions.
        import traceback

        traceback.print_exc()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="minibroker", description="Run minibroker")
    parser.add_argument("--host", default="127.0.0.1", help="listen host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=7379, help="listen port (default: 7379)")
    parser.add_argument(
        "--aof",
        default=".broker.aof",
        help="append-only file path (default: .broker.aof)",
    )
    parser.add_argument(
        "--no-aof",
        action="store_true",
        help="disable persistence (mainly useful for tests and ephemeral demos)",
    )
    parser.add_argument(
        "--retention",
        type=int,
        default=1000,
        help="retain last N messages per topic with no subscriber; 0 discards (default: 1000)",
    )
    parser.add_argument(
        "--max-client-queue",
        type=int,
        default=0,
        help="bounded per-connection queue; 0 means unlimited (default: 0)",
    )
    parser.add_argument(
        "--max-command-size",
        type=int,
        default=protocol.DEFAULT_MAX_FRAME_SIZE,
        help="maximum accepted wire frame in bytes (default: 1048576)",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.retention < 0:
        raise SystemExit("--retention must be >= 0")
    if args.max_client_queue < 0:
        raise SystemExit("--max-client-queue must be >= 0")
    if args.max_command_size < 64:
        raise SystemExit("--max-command-size must be at least 64")

    server = BrokerServer(
        host=args.host,
        port=args.port,
        retention=args.retention,
        max_client_queue=args.max_client_queue,
        aof_path=args.aof,
        aof_enabled=not args.no_aof,
        max_frame_size=args.max_command_size,
    )
    try:
        server.start()
        print(f"minibroker listening on {server.host}:{server.actual_port}")
        print(f"AOF: {'disabled' if args.no_aof else args.aof}")
        server.serve_forever()
    except KeyboardInterrupt:
        server.request_shutdown()
        server.completed_event.wait(10)
    return 0


# Imported here to avoid making network import fail during lightweight use.
from .persistence import AppendOnlyLog  # noqa: E402
