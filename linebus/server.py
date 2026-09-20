"""TCP network layer for the Linebus broker."""

from __future__ import annotations

import argparse
import errno
import socket
import threading
from typing import Dict, Optional, Tuple

from .broker import Broker, BrokerError, BrokerShutdown
from .protocol import (
    DEFAULT_MAX_COMMAND_SIZE,
    Frame,
    ProtocolError,
    CommandTooLargeError,
    encode_error,
    encode_event,
    encode_header,
    encode_ok,
    read_frame,
    validate_topic,
)


class Connection:
    def __init__(self, identifier: int, sock: socket.socket, address: Tuple[str, int]) -> None:
        self.identifier = identifier
        self.sock = sock
        self.address = address
        self.send_lock = threading.Lock()
        self.close_lock = threading.Lock()
        self.closed = False

    def send_raw(self, data: bytes) -> None:
        with self.send_lock:
            if self.closed:
                raise BrokenPipeError("connection closed")
            self.sock.sendall(data)

    def send_frame(self, frame: Frame, payload: bytes = b"") -> None:
        self.send_raw(encode_header(*frame.parts) + payload)

    def close(self) -> None:
        with self.close_lock:
            if self.closed:
                return
            self.closed = True
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


class LinebusServer:
    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 7379,
        *,
        retention: int = 1000,
        queue_capacity: int = 1000,
        queue_full_policy: str = "block",
        aof_path: str = ".linebus.aof",
        fsync: bool = False,
        max_command_size: int = DEFAULT_MAX_COMMAND_SIZE,
    ) -> None:
        self.host = host
        self.port = port
        self.max_command_size = max_command_size
        self.broker = Broker(
            retention=retention,
            queue_capacity=queue_capacity,
            queue_full_policy=queue_full_policy,
            aof_path=aof_path,
            fsync=fsync,
        )
        self._listen_sock: Optional[socket.socket] = None
        self._accept_thread: Optional[threading.Thread] = None
        self._connections: Dict[int, Connection] = {}
        self._threads: Dict[int, threading.Thread] = {}
        self._delivery_threads: Dict[int, threading.Thread] = {}
        self._state_lock = threading.Lock()
        self._next_connection_id = 1
        self._shutdown_event = threading.Event()
        self._stopped = False

    @property
    def actual_port(self) -> int:
        if self._listen_sock is None:
            raise RuntimeError("server is not started")
        return int(self._listen_sock.getsockname()[1])

    def start(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.host, self.port))
        sock.listen(128)
        self._listen_sock = sock
        self._accept_thread = threading.Thread(
            target=self._accept_loop, name="linebus-accept", daemon=True
        )
        self._accept_thread.start()

    def _accept_loop(self) -> None:
        assert self._listen_sock is not None
        while not self._shutdown_event.is_set():
            try:
                client_sock, address = self._listen_sock.accept()
            except OSError as exc:
                if self._shutdown_event.is_set() or exc.errno in (
                    errno.EBADF,
                    errno.EINVAL,
                    errno.ENOTCONN,
                ):
                    break
                raise
            if client_sock.family in (socket.AF_INET, socket.AF_INET6):
                try:
                    client_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                except OSError:
                    pass
            self._spawn_connection(client_sock, address)

    def _spawn_connection(self, sock: socket.socket, address: Tuple[str, int]) -> None:
        with self._state_lock:
            if self._shutdown_event.is_set():
                try:
                    sock.close()
                finally:
                    return
            connection_id = self._next_connection_id
            self._next_connection_id += 1
            connection = Connection(connection_id, sock, address)
            subscriber_id = self.broker.add_subscriber()
            self._connections[connection_id] = connection
            reader = threading.Thread(
                target=self._read_loop,
                args=(connection, subscriber_id),
                name=f"linebus-conn-{connection_id}",
                daemon=True,
            )
            delivery = threading.Thread(
                target=self._delivery_loop,
                args=(connection, subscriber_id),
                name=f"linebus-delivery-{connection_id}",
                daemon=True,
            )
            self._threads[connection_id] = reader
            self._delivery_threads[connection_id] = delivery
            delivery.start()
            reader.start()

    def _read_loop(self, connection: Connection, subscriber_id: int) -> None:
        try:
            # BufferedReader permits efficient header scanning while writes
            # still happen directly on the socket under a lock.
            stream = connection.sock.makefile("rb")
            try:
                while not self._shutdown_event.is_set():
                    try:
                        frame = read_frame(stream, self.max_command_size)
                    except socket.timeout:
                        continue
                    except CommandTooLargeError as exc:
                        self._safe_send(connection, encode_error(str(exc)))
                        # The parser drains a known payload; closing is still
                        # the safest action because clients cannot resend an
                        # individual framed command atomically.
                        break
                    except ProtocolError as exc:
                        self._safe_send(connection, encode_error(str(exc)))
                        break
                    if frame is None:
                        break
                    self._dispatch(connection, subscriber_id, frame)
            finally:
                try:
                    stream.close()
                except OSError:
                    pass
        except (ConnectionError, BrokenPipeError, OSError):
            pass
        except Exception:  # Defensive: one malformed connection must not stop server.
            pass
        finally:
            self._cleanup_connection(connection_id=connection.identifier, subscriber_id=subscriber_id)

    def _delivery_loop(self, connection: Connection, subscriber_id: int) -> None:
        try:
            while not self._shutdown_event.is_set():
                try:
                    event = self.broker.next_event(subscriber_id, timeout=0.2)
                except BrokerShutdown:
                    try:
                        self._safe_send(connection, encode_ok("SERVER_SHUTDOWN"))
                    except OSError:
                        # The SHUTDOWN requester or another worker may already
                        # be closing this exact socket; that is a clean race.
                        pass
                    break
                except BrokerError:
                    break
                if event is None:
                    continue
                try:
                    self._safe_send(
                        connection,
                        encode_event(event.sequence, event.topic, event.payload),
                    )
                except OSError:
                    break
        finally:
            # A dead delivery socket must unblock the command reader as well.
            connection.close()

    def _cleanup_connection(self, *, connection_id: int, subscriber_id: int) -> None:
        connection: Optional[Connection]
        with self._state_lock:
            connection = self._connections.pop(connection_id, None)
            # Keep completed threads in the registry until stop(); either worker
            # may finish at nearly the same time, and joining the peer from this
            # path can add an avoidable one-second shutdown delay per client.
        self.broker.remove_subscriber(subscriber_id)
        if connection is not None:
            connection.close()

    def _safe_send(self, connection: Connection, data: bytes) -> None:
        connection.send_raw(data)

    def _reply_error(self, connection: Connection, message: str) -> None:
        self._safe_send(connection, encode_error(message))

    def _dispatch(self, connection: Connection, subscriber_id: int, frame: Frame) -> None:
        command = frame.command
        try:
            if command == "PING" and len(frame.parts) == 1 and not frame.payload:
                connection.send_raw(encode_ok("PONG"))
            elif command == "PUBLISH":
                if len(frame.parts) != 3:
                    raise ProtocolError("usage: PUBLISH <topic> <length>")
                topic = validate_topic(frame.parts[1], allow_wildcard=False)
                event = self.broker.publish(topic, frame.payload)
                connection.send_raw(encode_header("OK", "PUBLISHED", str(event.sequence)))
            elif command == "SUBSCRIBE":
                if len(frame.parts) != 2 or frame.payload:
                    raise ProtocolError("usage: SUBSCRIBE <topic>")
                self.broker.subscribe(subscriber_id, frame.parts[1])
                connection.send_raw(encode_ok("SUBSCRIBED"))
            elif command == "UNSUBSCRIBE":
                if len(frame.parts) != 2 or frame.payload:
                    raise ProtocolError("usage: UNSUBSCRIBE <topic>")
                self.broker.unsubscribe(subscriber_id, frame.parts[1])
                connection.send_raw(encode_ok("UNSUBSCRIBED"))
            elif command == "STATS":
                if len(frame.parts) != 1 or frame.payload:
                    raise ProtocolError("usage: STATS")
                stats = self.broker.stats()
                body = " ".join(f"{key}={value}" for key, value in stats.items()).encode("ascii")
                connection.send_raw(encode_header("OK", "STATS", str(len(body))) + body)
            elif command == "FLUSH":
                if len(frame.parts) != 1 or frame.payload:
                    raise ProtocolError("usage: FLUSH")
                self.broker.flush()
                connection.send_raw(encode_ok("FLUSHED"))
            elif command == "SHUTDOWN":
                if len(frame.parts) != 1 or frame.payload:
                    raise ProtocolError("usage: SHUTDOWN")
                connection.send_raw(encode_ok("SHUTDOWN"))
                self.request_shutdown()
            else:
                raise ProtocolError(f"unknown command: {frame.parts[0]}")
        except (ProtocolError, BrokerError) as exc:
            try:
                self._reply_error(connection, str(exc))
            except OSError:
                connection.close()
        except BrokerShutdown:
            try:
                self._reply_error(connection, "server is shutting down")
            except OSError:
                connection.close()

    def request_shutdown(self) -> None:
        if self._shutdown_event.is_set():
            return
        self.broker.begin_shutdown()
        self._shutdown_event.set()
        listen_sock = self._listen_sock
        if listen_sock is not None:
            try:
                listen_sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def serve_forever(self) -> None:
        if self._accept_thread is None:
            raise RuntimeError("server is not started")
        while not self._shutdown_event.is_set():
            self._shutdown_event.wait(timeout=0.2)
        self.stop()

    def stop(self) -> None:
        with self._state_lock:
            if self._stopped:
                return
            self._stopped = True
        self.request_shutdown()
        if self._accept_thread is not None:
            self._accept_thread.join(timeout=2.0)
        with self._state_lock:
            delivery_threads = list(self._delivery_threads.values())
            reader_threads = list(self._threads.values())
            connections = list(self._connections.values())
        for thread in delivery_threads:
            if thread is not threading.current_thread():
                thread.join(timeout=2.0)
        for connection in connections:
            connection.close()
        for thread in reader_threads:
            if thread is not threading.current_thread():
                thread.join(timeout=2.0)
        if self._listen_sock is not None:
            try:
                self._listen_sock.close()
            except OSError:
                pass
        self.broker.close()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Linebus TCP event bus")
    parser.add_argument("--host", default="0.0.0.0", help="bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=7379, help="TCP port (default: 7379)")
    parser.add_argument(
        "--retention",
        type=int,
        default=1000,
        help="events retained per topic when no live consumer is ready; 0 disables retention",
    )
    parser.add_argument(
        "--queue-capacity",
        type=int,
        default=1000,
        help="per subscriber/topic live queue limit; 0 means unbounded",
    )
    parser.add_argument(
        "--queue-full-policy",
        choices=("block", "error"),
        default="block",
        help="behavior when a live subscriber queue is full (default: block)",
    )
    parser.add_argument("--aof", default=".linebus.aof", help="append-only file path")
    parser.add_argument(
        "--no-fsync",
        action="store_true",
        help="flush writes but do not fsync each event (faster, still crash-safe for most tests)",
    )
    parser.add_argument(
        "--max-command-size",
        type=int,
        default=DEFAULT_MAX_COMMAND_SIZE,
        help="maximum accepted command size in bytes",
    )
    return parser


def main(argv: Optional[list] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    server = LinebusServer(
        host=args.host,
        port=args.port,
        retention=args.retention,
        queue_capacity=args.queue_capacity,
        queue_full_policy=args.queue_full_policy,
        aof_path=args.aof,
        fsync=not args.no_fsync,
        max_command_size=args.max_command_size,
    )
    server.start()
    print(f"linebus listening on {args.host}:{server.actual_port} (aof={args.aof})", flush=True)

    def _signal_handler(signum, frame) -> None:  # pragma: no cover - signal path
        server.request_shutdown()

    import signal

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)
    try:
        server.serve_forever()
    finally:
        print("linebus stopped", flush=True)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
