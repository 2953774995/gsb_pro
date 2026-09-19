"""Multithreaded HTTP/1.1 server implemented with sockets."""

from __future__ import annotations

import argparse
import socket
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from time import monotonic
from typing import Optional

from .application import Application
from .errors import HTTPError, InternalServerError
from .parser import HTTPRequestParser
from .request import Request
from .response import make_error_response


class BufferedSocket:
    """A buffered byte reader that preserves exact HTTP message boundaries.

    Header parsing asks for one byte at a time.  Reading one byte from the
    kernel at a time would discard the natural over-read benefit of sockets,
    so this class performs a small bounded recv() into a queue.  Request body
    reads always drain that queue before reading from the kernel, which also
    preserves pipelined requests.
    """

    READ_CHUNK = 4096

    def __init__(self, sock: socket.socket) -> None:
        self.sock = sock
        self.buffer = bytearray()

    def _fill(self, wanted: int) -> None:
        # Header parsing asks for one byte, where a chunk is a performance
        # optimization.  Exact body reads must ask for no more than wanted,
        # because preserving bytes in this class is still a defensive measure;
        # stream sockets themselves never return more bytes than requested.
        amount = self.READ_CHUNK if wanted == 1 else min(self.READ_CHUNK, wanted)
        try:
            chunk = self.sock.recv(amount)
        except socket.timeout:
            raise TimeoutError("socket read timed out")
        self.buffer.extend(chunk)

    def read(self, size: int = -1) -> bytes:
        if size == 0:
            return b""
        if size is None or size < 0:
            try:
                chunk = self.sock.recv(self.READ_CHUNK)
            except socket.timeout:
                raise TimeoutError("socket read timed out")
            self.buffer.extend(chunk)
            data = bytes(self.buffer)
            self.buffer.clear()
            return data

        while len(self.buffer) < size:
            before = len(self.buffer)
            self._fill(size - before)
            if len(self.buffer) == before:
                # Peer closed before enough bytes were available.
                break
        take = min(size, len(self.buffer))
        data = bytes(self.buffer[:take])
        del self.buffer[:take]
        return data

    def sendall(self, data: bytes) -> None:
        self.sock.sendall(data)

    def close(self) -> None:
        # Do not shutdown the read side of a keep-alive socket: doing so can
        # cause TCP RSTs when the client still has bytes in flight.  Closing
        # the descriptor is enough; pending request bytes are intentionally
        # discarded when shutting the server down.
        try:
            self.sock.shutdown(socket.SHUT_WR)
        except OSError:
            pass
        self.sock.close()


def should_keep_alive(request: Request) -> bool:
    connection = (request.headers.get("connection") or "").lower()
    tokens = {token.strip() for token in connection.split(",") if token.strip()}
    if "close" in tokens:
        return False
    if request.version == "HTTP/1.0":
        return "keep-alive" in tokens
    return True


class Server:
    def __init__(
        self,
        app: Application,
        host: str = "127.0.0.1",
        port: int = 0,
        workers: int = 16,
        timeout: float = 30.0,
        max_header_size: int = 8192,
        max_body_size: int = 16 * 1024 * 1024,
        backlog: int = 128,
        access_log: bool = True,
    ) -> None:
        self.app = app
        self.host = host
        self.timeout = timeout
        self.max_header_size = max_header_size
        self.max_body_size = max_body_size
        self.access_log = access_log
        self.workers = max(1, workers)
        self.running = threading.Event()
        self._connections = set()
        self._connections_lock = threading.Lock()
        self._serve_thread: Optional[threading.Thread] = None
        self._pool: Optional[ThreadPoolExecutor] = None
        self.backlog = backlog

        self.socket = self.create_listen_socket(host, port, backlog)
        self.bound_host, self.bound_port = self.socket.getsockname()[:2]

    @staticmethod
    def create_listen_socket(
        host: str, port: int, backlog: int
    ) -> socket.socket:
        listen_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listen_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listen_socket.bind((host, port))
        listen_socket.listen(backlog)
        listen_socket.settimeout(0.5)
        return listen_socket

    @property
    def address(self) -> str:
        host = self.bound_host if self.bound_host != "0.0.0.0" else "127.0.0.1"
        return f"http://{host}:{self.bound_port}"

    def start(self, daemon: bool = False) -> None:
        if self.running.is_set():
            return
        self.running.set()
        self._pool = ThreadPoolExecutor(
            max_workers=self.workers,
            thread_name_prefix="miniweb-worker",
        )
        self._serve_thread = threading.Thread(
            target=self.serve_forever, name="miniweb-acceptor", daemon=daemon
        )
        self._serve_thread.start()

    def serve_forever(self) -> None:
        self.running.set()
        if self._pool is None:
            self._pool = ThreadPoolExecutor(
                max_workers=self.workers,
                thread_name_prefix="miniweb-worker",
            )
        while self.running.is_set():
            try:
                conn, addr = self.socket.accept()
            except socket.timeout:
                continue
            except InterruptedError:
                continue
            except OSError:
                if self.running.is_set():
                    continue
                break
            conn.settimeout(self.timeout)
            with self._connections_lock:
                if not self.running.is_set():
                    conn.close()
                    break
                self._connections.add(conn)
            assert self._pool is not None
            try:
                self._pool.submit(self._handle_connection, conn, addr)
            except RuntimeError:
                # Executor was shut down during a concurrent shutdown call.
                with self._connections_lock:
                    self._connections.discard(conn)
                conn.close()
                break

    def shutdown(self, wait: bool = True) -> None:
        if not self.running.is_set() and not self._serve_thread:
            return
        self.running.clear()
        try:
            self.socket.close()
        except OSError:
            pass
        with self._connections_lock:
            connections = list(self._connections)
        for conn in connections:
            try:
                conn.close()
            except OSError:
                pass
        if self._serve_thread is not None:
            self._serve_thread.join(timeout=2.0)
        if self._pool is not None:
            # Pending work becomes harmless once sockets are closed.  Do not
            # use cancel_futures so behavior is unchanged on Python 3.8/3.9.
            self._pool.shutdown(wait=wait)

    def _handle_connection(self, conn: socket.socket, addr) -> None:
        stream = BufferedSocket(conn)
        remote = addr[0] if addr else "-"
        try:
            while self.running.is_set():
                request: Optional[Request] = None
                start = monotonic()
                method = "-"
                target = "-"
                status = 500
                parser = HTTPRequestParser(
                    stream,
                    max_header_size=self.max_header_size,
                    max_body_size=self.max_body_size,
                )
                try:
                    request = parser.parse(remote_address=remote)
                    method = request.method
                    target = request.raw_path
                    if request.query_string:
                        target += "?" + request.query_string
                    keep_alive = should_keep_alive(request)
                    response = self.app.handle(request, keep_alive=keep_alive)
                    response.version = request.version
                    response.keep_alive = keep_alive
                    try:
                        wire_response = response.serialize()
                    except Exception:
                        # Serialization happens before any bytes are sent, so
                        # a bad application response can still be replaced.
                        sys.stderr.write(
                            "miniweb: response serialization failed\n"
                        )
                        response = make_error_response(InternalServerError())
                        response.version = request.version
                        response.keep_alive = False
                        keep_alive = False
                        wire_response = response.serialize()
                    status = response.status
                    stream.sendall(wire_response)
                    self._log(remote, method, target, status, start)
                    if not keep_alive:
                        break
                except HTTPError as error:
                    status = error.status
                    response = make_error_response(error, head=False)
                    # Parse errors are connection-unsafe: close after response.
                    response.keep_alive = False
                    try:
                        stream.sendall(response.serialize())
                    except OSError:
                        # The client may have already closed after a malformed
                        # or oversized request; this is normal, not a crash.
                        break
                    finally:
                        self._log(remote, method, target, status, start)
                    break
                except (socket.timeout, TimeoutError):
                    break
                except (ConnectionError, OSError):
                    break
        except Exception:
            # A worker must never propagate into the executor/process.  Keep
            # unexpected worker errors bounded; application exceptions are
            # already converted to safe 500 responses above.
            pass
        finally:
            with self._connections_lock:
                self._connections.discard(conn)
            stream.close()

    def _log(self, remote: str, method: str, path: str, status: int, start: float) -> None:
        if not self.access_log:
            return
        elapsed_ms = (monotonic() - start) * 1000.0
        timestamp = datetime.now().isoformat(timespec="milliseconds")
        print(
            f"{timestamp} {remote} {method} {path} {status} {elapsed_ms:.2f}ms",
            flush=True,
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="miniweb", description="Run miniweb server")
    parser.add_argument("--host", default="127.0.0.1", help="bind host")
    parser.add_argument("--port", type=int, default=8000, help="bind port")
    parser.add_argument("--root", help="static files root directory")
    parser.add_argument("--workers", type=int, default=16, help="worker thread count")
    parser.add_argument("--timeout", type=float, default=30.0, help="idle timeout")
    return parser
