"""Multi-threaded HTTP/1.1 server built on raw sockets."""

import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from .errors import ConnectionClosed, HTTPError
from .request import MAX_BODY_BYTES, MAX_HEADER_BYTES, SocketReader, read_request
from .response import Response


class HTTPServer:
    """Thread-pooled HTTP server with keep-alive and idle timeouts."""

    def __init__(self, app, host="127.0.0.1", port=8080, workers=16,
                 timeout=30.0, max_header_bytes=MAX_HEADER_BYTES,
                 max_body_bytes=MAX_BODY_BYTES):
        self.app = app
        self.host = host
        self.timeout = timeout
        self.max_header_bytes = max_header_bytes
        self.max_body_bytes = max_body_bytes
        self._stopping = threading.Event()
        self._connections = set()
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=workers)
        self._thread = None

        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind((host, port))
        self._listener.listen(128)
        self._listener.settimeout(0.5)

    @property
    def server_address(self):
        return self._listener.getsockname()[:2]

    @property
    def port(self):
        return self.server_address[1]

    def start(self):
        """Start serving in a background thread."""
        self._thread = threading.Thread(target=self.serve_forever, daemon=True)
        self._thread.start()
        return self

    def serve_forever(self):
        """Accept loop; runs until shutdown() is called."""
        while not self._stopping.is_set():
            try:
                conn, addr = self._listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            self._pool.submit(self._serve_connection, conn, addr)

    def shutdown(self):
        """Stop accepting new connections and close existing ones."""
        self._stopping.set()
        try:
            self._listener.close()
        except OSError:
            pass
        with self._lock:
            conns = list(self._connections)
        for conn in conns:
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                conn.close()
            except OSError:
                pass
        self._pool.shutdown(wait=False)
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=5)

    def _serve_connection(self, conn, addr):
        with self._lock:
            self._connections.add(conn)
        try:
            conn.settimeout(self.timeout)
            reader = SocketReader(conn)
            while not self._stopping.is_set():
                try:
                    request = read_request(
                        reader,
                        max_header_bytes=self.max_header_bytes,
                        max_body_bytes=self.max_body_bytes,
                    )
                except ConnectionClosed:
                    break
                except HTTPError as exc:
                    self._send(conn, Response.error(exc.status, exc.message, exc.headers),
                               head_only=False, keep_alive=False)
                    self._log(addr, "-", "-", exc.status, 0.0)
                    break
                except (socket.timeout, OSError):
                    break

                started = time.monotonic()
                response = self.app.handle(request)
                keep_alive = request.keep_alive()
                self._send(conn, response,
                           head_only=(request.method == "HEAD"),
                           keep_alive=keep_alive)
                elapsed_ms = (time.monotonic() - started) * 1000.0
                self._log(addr, request.method, request.raw_target,
                          response.status, elapsed_ms)
                if not keep_alive:
                    break
        finally:
            with self._lock:
                self._connections.discard(conn)
            try:
                conn.close()
            except OSError:
                pass

    @staticmethod
    def _send(conn, response, head_only, keep_alive):
        try:
            conn.sendall(response.to_bytes(head_only=head_only, keep_alive=keep_alive))
        except OSError:
            pass

    @staticmethod
    def _log(addr, method, path, status, elapsed_ms):
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print("%s %s:%s %s %s -> %d %.2fms"
              % (stamp, addr[0], addr[1], method, path, status, elapsed_ms),
              flush=True)
