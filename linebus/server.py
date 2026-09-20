"""Multi-threaded TCP server for linebus."""

from __future__ import annotations

import argparse
import logging
import socket
import threading
from typing import Optional

from .aof import AOFError, AppendOnlyLog
from .broker import (
    Broker,
    FULL_BLOCK,
    FULL_REJECT,
    InvalidTopic,
    OutboxClosed,
    QueueFull,
)
from .protocol import (
    DEFAULT_MAX_COMMAND_SIZE,
    CommandTooLargeError,
    ProtocolParseError,
    encode_bye,
    encode_error,
    encode_ok,
    encode_stats,
)

LOGGER = logging.getLogger("linebus")


class ClientSession:
    def __init__(
        self,
        server: "LinebusServer",
        conn: socket.socket,
        address,
        outbox,
        parser,
    ):
        self.server = server
        self.conn = conn
        self.address = address
        self.outbox = outbox
        self.parser = parser
        self.send_lock = threading.Lock()
        self.writer_thread = threading.Thread(target=self._writer_loop, name=f"linebus-writer-{outbox.connection_id}", daemon=True)
        self.reader_thread = threading.Thread(target=self._reader_loop, name=f"linebus-reader-{outbox.connection_id}", daemon=True)
        self.finished = threading.Event()

    def start(self) -> None:
        self.writer_thread.start()
        self.reader_thread.start()

    def _reader_loop(self) -> None:
        fatal = False
        try:
            while not self.server.shutdown_event.is_set() and not self.outbox.closed:
                try:
                    data = self.conn.recv(65536)
                except OSError:
                    break
                if not data:
                    break
                try:
                    messages = self.parser.feed(data)
                except CommandTooLargeError as exc:
                    self._send_fatal_error(str(exc))
                    fatal = True
                    break
                except ProtocolParseError as exc:
                    self._send_fatal_error(str(exc))
                    fatal = True
                    break
                for message in messages:
                    self._handle_message(message)
                    if self.server.shutdown_event.is_set() or self.outbox.closed:
                        break
        except Exception:
            LOGGER.exception("session %s failed", self.address)
            fatal = True
        finally:
            self._finish(fatal=fatal)

    def _handle_message(self, message) -> None:
        command = message.command.upper()
        try:
            if command == "PING":
                if message.topic is not None:
                    self.reply_error("PING accepts no arguments")
                else:
                    self.reply(b"OK PONG\n")
            elif command in {"SUBSCRIBE", "UNSUBSCRIBE"}:
                if not message.topic:
                    self.reply_error(f"{command} requires a topic")
                    return
                if command == "SUBSCRIBE":
                    self.server.broker.subscribe(self.outbox, message.topic)
                    self.reply(encode_ok(f"SUBSCRIBED {message.topic}"))
                else:
                    self.server.broker.unsubscribe(self.outbox, message.topic)
                    self.reply(encode_ok(f"UNSUBSCRIBED {message.topic}"))
            elif command == "PUBLISH":
                if not message.topic:
                    self.reply_error("PUBLISH requires <topic> <length>")
                    return
                event = self.server.broker.publish(message.topic, message.payload)
                self.reply(encode_ok(f"SEQ {event.sequence}"))
            elif command == "STATS":
                if message.topic is not None:
                    self.reply_error("STATS accepts no arguments")
                else:
                    self.reply(encode_stats(self.server.broker.stats()))
            elif command == "FLUSH":
                if message.topic is not None:
                    self.reply_error("FLUSH accepts no arguments")
                else:
                    self.server.broker.flush()
                    self.reply(encode_ok("FLUSHED"))
            elif command == "SHUTDOWN":
                if message.topic is not None:
                    self.reply_error("SHUTDOWN accepts no arguments")
                else:
                    self.reply(encode_ok("SHUTDOWN"))
                    self.server.request_shutdown()
            else:
                self.reply_error(f"unknown command: {message.command}")
        except InvalidTopic as exc:
            self.reply_error(str(exc))
        except QueueFull as exc:
            self.reply_error(str(exc))
        except OutboxClosed:
            # Shutdown/disconnect: no useful place to send the response.
            return
        except AOFError as exc:
            self.reply_error(str(exc))
        except Exception as exc:  # Defensive: one bad command must not kill server.
            LOGGER.exception("command failed")
            self.reply_error(f"internal error: {exc}")

    def reply(self, frame: bytes) -> None:
        self.outbox.put_control(frame)

    def reply_error(self, message: str) -> None:
        self.reply(encode_error(message))

    def _send_fatal_error(self, message: str) -> None:
        # A fatal parse error closes the stream immediately. Bypass the normal
        # control queue so the reader finishing cannot remove/discard the ERR.
        try:
            with self.send_lock:
                self.conn.sendall(encode_error(message))
        except OSError:
            pass

    def _writer_loop(self) -> None:
        while True:
            frame = self.outbox.get(0.2)
            if frame is None:
                if self.outbox.closed and not self.outbox.events and not self.outbox.control:
                    return
                continue
            try:
                with self.send_lock:
                    self.conn.sendall(frame)
            except OSError:
                self.outbox.close(clear=True)
                return

    def _finish(self, *, fatal: bool) -> None:
        if self.finished.is_set():
            return
        self.finished.set()
        self.server.remove_session(self)
        shutting_down = self.server.shutdown_event.is_set()
        if shutting_down:
            # BYE is already in the outbox. Give events a short drain period.
            self.writer_thread.join(2.0)
        else:
            # Remove subscriptions before shutdown(SHUT_RDWR) so a blocked
            # publisher cannot be unblocked into a half-closed outbox.
            self.server.broker.remove_connection(self.outbox)
            self.writer_thread.join(1.0)
        try:
            self.conn.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.conn.close()

    def graceful_notify(self) -> None:
        self.outbox.close(notify=True)
        try:
            self.conn.shutdown(socket.SHUT_RD)
        except OSError:
            pass


class LinebusServer:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 7379,
        *,
        aof_path: str = ".linebus.aof",
        retention: int = 1000,
        queue_capacity: int = 1000,
        full_strategy: str = FULL_REJECT,
        max_command_size: int = DEFAULT_MAX_COMMAND_SIZE,
    ):
        self.host = host
        self.port = port
        self.aof_path = aof_path
        self.max_command_size = max_command_size
        self.aof = AppendOnlyLog(aof_path)
        self.aof.initialize()
        self.broker = Broker(
            self.aof,
            retention=retention,
            queue_capacity=queue_capacity,
            full_strategy=full_strategy,
        )
        self.broker.restore()
        self._socket: Optional[socket.socket] = None
        self._sessions: set[ClientSession] = set()
        self._state_lock = threading.RLock()
        self.shutdown_event = threading.Event()
        self._accept_thread: Optional[threading.Thread] = None

    @property
    def socket(self) -> Optional[socket.socket]:
        return self._socket

    def start(self) -> None:
        """Bind and start accepting connections in a background thread."""

        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((self.host, self.port))
        server.listen(128)
        self._socket = server
        self.port = server.getsockname()[1]
        self.shutdown_event.clear()
        self._accept_thread = threading.Thread(target=self.serve_forever, name="linebus-accept", daemon=True)
        self._accept_thread.start()

    def serve_forever(self) -> None:
        assert self._socket is not None
        while not self.shutdown_event.is_set():
            try:
                conn, address = self._socket.accept()
            except OSError:
                if self.shutdown_event.is_set():
                    break
                LOGGER.exception("accept failed")
                break
            self._set_socket_options(conn)
            session = self.attach_socket(conn, address)
            if session is None:
                break
            session.start()

    def attach_socket(self, conn: socket.socket, address) -> Optional[ClientSession]:
        """Attach one connected stream and start its session bookkeeping."""

        with self._state_lock:
            if self.shutdown_event.is_set():
                conn.close()
                return None
            from .protocol import ProtocolParser

            outbox = self.broker.create_outbox()
            session = ClientSession(
                self,
                conn,
                address,
                outbox,
                ProtocolParser(self.max_command_size),
            )
            self._sessions.add(session)
        return session

    @staticmethod
    def _set_socket_options(conn: socket.socket) -> None:
        try:
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            # AF_UNIX/socketpair test streams have no TCP_NODELAY option.
            pass

    def remove_session(self, session: ClientSession) -> None:
        with self._state_lock:
            self._sessions.discard(session)

    def request_shutdown(self) -> None:
        with self._state_lock:
            if self.shutdown_event.is_set():
                return
            self.shutdown_event.set()
            sessions = list(self._sessions)
            listening = self._socket
        for session in sessions:
            session.graceful_notify()
        if listening is not None:
            try:
                listening.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                listening.close()
            except OSError:
                pass

    def wait_closed(self, timeout: Optional[float] = 5.0) -> None:
        if self._accept_thread is not None:
            self._accept_thread.join(timeout)
        with self._state_lock:
            sessions = list(self._sessions)
        for session in sessions:
            session.reader_thread.join(timeout)
            session.writer_thread.join(timeout)
        self.aof.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="linebus-server", description="Run the linebus TCP event bus")
    parser.add_argument("--host", default="127.0.0.1", help="bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=7379, help="TCP port (default: 7379)")
    parser.add_argument("--aof", default=".linebus.aof", help="append-only file path")
    parser.add_argument("--retention", type=int, default=1000, help="retained events per topic; 0 disables retention")
    parser.add_argument("--queue-capacity", type=int, default=1000, help="per-connection subscriber queue capacity")
    parser.add_argument(
        "--on-full",
        choices=(FULL_REJECT, FULL_BLOCK),
        default=FULL_REJECT,
        help="behavior when a slow subscriber queue is full",
    )
    parser.add_argument("--max-command-size", type=int, default=DEFAULT_MAX_COMMAND_SIZE, help="maximum frame size in bytes")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    server = LinebusServer(
        host=args.host,
        port=args.port,
        aof_path=args.aof,
        retention=args.retention,
        queue_capacity=args.queue_capacity,
        full_strategy=args.on_full,
        max_command_size=args.max_command_size,
    )
    server.start()
    LOGGER.info("linebus listening on %s:%s (AOF=%s)", args.host, server.port, args.aof)
    try:
        server.shutdown_event.wait()
    except KeyboardInterrupt:
        server.request_shutdown()
    server.wait_closed()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
