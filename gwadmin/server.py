"""Multi-threaded HTTP server built on raw sockets.

One thread per accepted connection (bounded by a semaphore sized with
--workers), HTTP/1.1 keep-alive with idle timeout, graceful shutdown on
SIGINT/SIGTERM, and an access log on stdout.
"""

import socket
import sys
import threading
import time

from .http import (HTTPError, default_error_page, error_response,
                   read_request, serialize_response)

CRLF = b"\r\n"


class GatewayServer(object):
    def __init__(self, app, host="127.0.0.1", port=8080, workers=4,
                 idle_timeout=30.0, log_file=None):
        self.app = app
        self.host = host
        self.port = port
        self.workers = workers
        self.idle_timeout = idle_timeout
        self.log_file = log_file if log_file is not None else sys.stdout

        self._shutdown = threading.Event()
        self._slots = threading.Semaphore(max(1, workers) * 8)
        self._connections = set()
        self._connections_lock = threading.Lock()
        self._threads = []
        self._sock = None

    # -- lifecycle ---------------------------------------------------------
    def start(self):
        """Bind + listen. Returns the actual bound port."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.host, self.port))
        sock.listen(128)
        sock.settimeout(0.5)
        self._sock = sock
        self.port = sock.getsockname()[1]
        return self.port

    def serve_forever(self):
        if self._sock is None:
            self.start()
        try:
            while not self._shutdown.is_set():
                try:
                    conn, addr = self._sock.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break  # socket closed during shutdown
                if not self._slots.acquire(blocking=False):
                    # Server saturated: reject politely.
                    try:
                        conn.sendall(error_response(
                            503, "server busy", keep_alive=False))
                    except OSError:
                        pass
                    conn.close()
                    continue
                thread = threading.Thread(
                    target=self._connection_worker,
                    args=(conn, addr),
                    daemon=True,
                    name="gwadmin-conn-%s" % (addr[1],),
                )
                with self._connections_lock:
                    self._connections.add(conn)
                self._threads.append(thread)
                thread.start()
        finally:
            self._reap_threads()

    def shutdown(self):
        """Stop accepting new connections and close existing ones."""
        self._shutdown.set()
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        with self._connections_lock:
            conns = list(self._connections)
        for conn in conns:
            _force_close(conn)
        self._reap_threads()

    # context-manager sugar for tests
    def __enter__(self):
        self.start()
        threading.Thread(target=self.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self.shutdown()

    def _reap_threads(self):
        for thread in self._threads:
            thread.join(timeout=2.0)

    # -- per-connection ------------------------------------------------------
    def _connection_worker(self, conn, addr):
        try:
            conn.settimeout(self.idle_timeout)
            reader = conn.makefile("rb")
            try:
                self._serve_connection(conn, reader, addr)
            finally:
                try:
                    reader.close()
                except OSError:
                    pass
        finally:
            with self._connections_lock:
                self._connections.discard(conn)
            _force_close(conn)
            self._slots.release()

    def _serve_connection(self, conn, reader, addr):
        while not self._shutdown.is_set():
            try:
                request = read_request(reader, remote_addr=addr)
            except HTTPError as exc:
                self._send(conn, error_response(
                    exc.status, exc.message, keep_alive=False))
                self._log(addr, "-", "-", exc.status, 0.0)
                return
            except (socket.timeout, TimeoutError):
                return  # idle timeout: close quietly
            except (ConnectionResetError, BrokenPipeError, OSError):
                return
            except Exception:
                # Never let a parse-level surprise kill the process.
                self._send(conn, error_response(400, "Bad Request",
                                                keep_alive=False))
                return

            if request is None:
                return  # peer closed idle keep-alive connection

            started = time.monotonic()
            head_only = request.method == "HEAD"
            try:
                status, headers, body = self.app.handle(request)
            except HTTPError as exc:
                payload = error_response(exc.status, exc.message,
                                         head_only=head_only,
                                         keep_alive=request.keep_alive)
                elapsed = (time.monotonic() - started) * 1000.0
                if not self._send(conn, payload):
                    return
                self._log(addr, request.method, request.raw_target,
                          exc.status, elapsed)
                if not request.keep_alive:
                    return
                continue
            except Exception:
                # Unified 500 fallback: no stack traces to the client.
                payload = error_response(500, "Internal Server Error",
                                         head_only=head_only,
                                         keep_alive=False)
                self._send(conn, payload)
                elapsed = (time.monotonic() - started) * 1000.0
                self._log(addr, request.method, request.raw_target,
                          500, elapsed)
                return

            if body is None and status >= 400:
                body = default_error_page(status)
            payload = serialize_response(
                status, headers, body,
                head_only=head_only,
                keep_alive=request.keep_alive)
            elapsed = (time.monotonic() - started) * 1000.0
            if not self._send(conn, payload):
                return
            self._log(addr, request.method, request.raw_target, status,
                      elapsed)
            if not request.keep_alive:
                return

    # -- helpers ---------------------------------------------------------------
    @staticmethod
    def _send(conn, payload):
        try:
            conn.sendall(payload)
            return True
        except OSError:
            return False

    def _log(self, addr, method, path, status, elapsed_ms):
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        line = '%s %s:%s "%s %s" -> %d %.1fms\n' % (
            timestamp, addr[0] if addr else "-",
            addr[1] if addr else 0, method, path, status, elapsed_ms)
        try:
            self.log_file.write(line)
            self.log_file.flush()
        except Exception:
            pass


def _force_close(conn):
    try:
        conn.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    try:
        conn.close()
    except OSError:
        pass
