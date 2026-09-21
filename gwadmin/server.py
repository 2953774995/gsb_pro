"""Multi-threaded socket server implementing the HTTP connection lifecycle."""

import logging
import socket
import threading
import time

from .constants import (
    DEFAULT_BODY_LIMIT,
    DEFAULT_HEADER_LIMIT,
    DEFAULT_IDLE_TIMEOUT,
    LISTEN_BACKLOG,
)
from .errors import BadRequest, PayloadTooLarge
from .protocol import (
    build_error_response,
    build_response,
    default_error_page,
    read_request,
    wants_keep_alive,
)

LOGGER = logging.getLogger("gwadmin.access")


class BufferedSocket:
    """Socket wrapper with a small internal receive buffer."""

    def __init__(self, sock, peer=None):
        self.sock = sock
        self.peer = peer
        self._buffer = bytearray()

    def recv(self, size):
        if size <= 0:
            return b""
        if not self._buffer:
            data = self.sock.recv(max(size, 65536))
            if not data:
                return b""
            self._buffer.extend(data)
        chunk = bytes(self._buffer[:size])
        del self._buffer[:size]
        return chunk

    def sendall(self, data):
        self.sock.sendall(data)

    def settimeout(self, value):
        self.sock.settimeout(value)

    def shutdown(self, how=socket.SHUT_RDWR):
        try:
            self.sock.shutdown(how)
        except OSError:
            pass

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


class HTTPServer:
    def __init__(
        self,
        app,
        host="0.0.0.0",
        port=8080,
        workers=16,
        idle_timeout=DEFAULT_IDLE_TIMEOUT,
        header_limit=DEFAULT_HEADER_LIMIT,
        body_limit=DEFAULT_BODY_LIMIT,
    ):
        self.app = app
        self.host = host
        self.port = port
        self.workers = max(1, int(workers))
        self.idle_timeout = idle_timeout
        self.header_limit = header_limit
        self.body_limit = body_limit
        self.server_sock = None
        self._worker_slots = threading.BoundedSemaphore(self.workers)
        self._connection_threads = []
        self.stop_event = threading.Event()
        self._clients_lock = threading.Lock()
        self._clients = set()

    def socket_pair(self):
        family = socket.AF_INET6 if ":" in self.host else socket.AF_INET
        sock = socket.socket(family, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.host, self.port))
        sock.listen(LISTEN_BACKLOG)
        sock.settimeout(0.5)
        self.server_sock = sock
        self.host, self.port = sock.getsockname()[:2]
        return sock

    def install_signal_handlers(self):
        import signal

        def handle_stop(signum, frame):
            self.stop_event.set()

        signal.signal(signal.SIGINT, handle_stop)
        signal.signal(signal.SIGTERM, handle_stop)

    def serve_forever(self):
        if self.server_sock is None:
            self.socket_pair()
        # The task model is one OS thread per accepted connection, matching
        # the CLI worker count. A semaphore provides backpressure without a
        # queue of sockets that would be untracked during shutdown.
        try:
            while not self.stop_event.is_set():
                try:
                    client, addr = self.server_sock.accept()
                except socket.timeout:
                    continue
                except OSError:
                    if self.stop_event.is_set():
                        break
                    raise
                client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                client.settimeout(self.idle_timeout)
                wrapper = BufferedSocket(client, addr)
                if not self._worker_slots.acquire(blocking=False):
                    self._reject_busy(wrapper)
                    continue
                with self._clients_lock:
                    self._clients.add(wrapper)
                    self._connection_threads = [
                        thread for thread in self._connection_threads if thread.is_alive()
                    ]
                thread = threading.Thread(
                    target=self._run_connection, args=(wrapper,), daemon=True, name="gwadmin-conn"
                )
                with self._clients_lock:
                    self._connection_threads.append(thread)
                thread.start()
        finally:
            self.shutdown()


    def _reject_busy(self, client):
        try:
            client.sendall(
                build_error_response(
                    None,
                    503,
                    "Server Busy",
                    {"Retry-After": "1"},
                    keep_alive=False,
                )
            )
        except OSError:
            pass
        client.close()

    def shutdown(self):
        self.stop_event.set()
        if self.server_sock is not None:
            try:
                self.server_sock.close()
            except OSError:
                pass
        with self._clients_lock:
            clients = list(self._clients)
        for client in clients:
            client.shutdown(socket.SHUT_RDWR)
        # Active sockets have been shut down above, which interrupts their
        # blocking I/O. Join briefly; daemon threads prevent shutdown hangs in
        # abnormal platform socket implementations.
        with self._clients_lock:
            threads = list(self._connection_threads)
        for thread in threads:
            if thread is not threading.current_thread():
                thread.join(timeout=1.0)
        for client in clients:
            client.close()

    @staticmethod
    def _log(started, method, path, status):
        elapsed_ms = (time.monotonic() - started) * 1000.0
        LOGGER.info("%s %s %s %.3fms", method, path, status, elapsed_ms)

    def _send_error(self, client, request, error, keep_alive=False):
        try:
            data = build_error_response(
                request, error.status, error.message, error.headers, keep_alive
            )
            client.sendall(data)
        except OSError:
            return False
        return keep_alive

    def _handle_one_request(self, client):
        started = time.monotonic()
        try:
            request = read_request(
                client, header_limit=self.header_limit, body_limit=self.body_limit
            )
        except EOFError:
            return False
        except (BadRequest, PayloadTooLarge) as exc:
            partial = getattr(exc, "request", None)
            self._log(started, partial.method if partial else "-", partial.target if partial else "-", exc.status)
            self._send_error(client, partial, exc, False)
            return False
        except (OSError, socket.timeout):
            return False

        self.app.state.count_request()
        keep_alive = wants_keep_alive(request)
        try:
            status, headers, body = self.app.handle(request)
            if body is None and status >= 400:
                body = default_error_page(status)
            client.sendall(
                build_response(request, status, headers, body, keep_alive=keep_alive)
            )
        except Exception:
            LOGGER.exception("Unhandled request error")
            try:
                client.sendall(build_error_response(request, 500, keep_alive=False))
            except OSError:
                pass
            return False
        self._log(started, request.method, request.target, status)
        return keep_alive

    def _run_connection(self, client):
        try:
            self._handle_connection(client)
        finally:
            try:
                self._worker_slots.release()
            except ValueError:
                pass

    def _handle_connection(self, client):
        try:
            while not self.stop_event.is_set():
                if not self._handle_one_request(client):
                    break
        except Exception:
            LOGGER.exception("Fatal connection-level error")
        finally:
            with self._clients_lock:
                self._clients.discard(client)
            client.close()
