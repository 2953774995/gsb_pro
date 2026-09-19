"""Multi-threaded HTTP/1.1 server built on raw sockets."""

import socket
import sys
import threading
import time

from .errors import RequestError
from .request import (MAX_BODY, MAX_HEADERS, MAX_REQUEST_LINE, read_request)
from .response import build_response, reason_phrase


class HTTPServer(object):
    """Thread-per-connection HTTP server with a worker limit,
    keep-alive, idle timeouts and clean shutdown."""

    def __init__(self, host, port, app, workers=32, idle_timeout=30.0,
                 max_request_line=MAX_REQUEST_LINE, max_headers=MAX_HEADERS,
                 max_body=MAX_BODY, access_log=None):
        self.host = host
        self.port = port
        self.app = app
        self.workers = workers
        self.idle_timeout = idle_timeout
        self.max_request_line = max_request_line
        self.max_headers = max_headers
        self.max_body = max_body
        self.access_log = access_log if access_log is not None else sys.stdout

        self._sock = None
        self._stopping = threading.Event()
        self._slots = threading.Semaphore(workers)
        self._threads = set()
        self._conns = set()
        self._lock = threading.Lock()

    # -- lifecycle ------------------------------------------------------------
    def serve_forever(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((self.host, self.port))
        self._sock.listen(128)
        self._sock.settimeout(0.5)
        self.host, self.port = self._sock.getsockname()[:2]
        try:
            while not self._stopping.is_set():
                try:
                    conn, addr = self._sock.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break  # socket closed by shutdown()
                self._slots.acquire()
                if self._stopping.is_set():
                    self._slots.release()
                    conn.close()
                    break
                t = threading.Thread(target=self._connection_runner,
                                     args=(conn, addr), daemon=True)
                with self._lock:
                    self._threads.add(t)
                t.start()
        finally:
            self._stopping.set()
            try:
                self._sock.close()
            except OSError:
                pass

    def shutdown(self, wait=True, timeout=5.0):
        """Stop accepting new connections and close existing ones."""
        self._stopping.set()
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        with self._lock:
            conns = list(self._conns)
        for conn in conns:
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                conn.close()
            except OSError:
                pass
        if wait:
            deadline = time.time() + timeout
            with self._lock:
                threads = list(self._threads)
            for t in threads:
                remaining = deadline - time.time()
                if remaining <= 0:
                    break
                t.join(remaining)

    # -- per-connection ---------------------------------------------------------
    def _connection_runner(self, conn, addr):
        try:
            with self._lock:
                self._conns.add(conn)
            self._serve_connection(conn, addr)
        finally:
            with self._lock:
                self._conns.discard(conn)
            try:
                conn.close()
            except OSError:
                pass
            self._slots.release()
            with self._lock:
                self._threads.discard(threading.current_thread())

    def _serve_connection(self, conn, addr):
        conn.settimeout(self.idle_timeout)
        try:
            rfile = conn.makefile("rb")
        except OSError:
            return
        while not self._stopping.is_set():
            try:
                request = read_request(
                    rfile, conn=conn,
                    max_request_line=self.max_request_line,
                    max_headers=self.max_headers,
                    max_body=self.max_body,
                    client_addr=addr)
            except RequestError as exc:
                self._send(conn, build_response(
                    exc.status, [], None, version="HTTP/1.1",
                    keep_alive=False, message=exc.message))
                self._log(addr, "-", "-", exc.status, 0.0)
                return
            except (socket.timeout, TimeoutError):
                return  # idle timeout -> close
            except (ConnectionError, OSError):
                return
            except Exception:
                # Never let a parsing bug kill the server.
                self._send(conn, build_response(
                    400, [], None, version="HTTP/1.1", keep_alive=False))
                return

            if request is None:
                return  # peer closed cleanly

            started = time.monotonic()
            try:
                status, headers, body = self.app.handle(request)
            except Exception:  # app.handle already guards; belt & braces
                status, headers, body = 500, [], None
            keep_alive = not request.wants_close() and not self._stopping.is_set()
            payload = build_response(
                status, headers, body, method=request.method,
                version=request.version, keep_alive=keep_alive)
            if not self._send(conn, payload):
                return
            elapsed_ms = (time.monotonic() - started) * 1000.0
            self._log(addr, request.method, request.target, status, elapsed_ms)
            if not keep_alive:
                return

    @staticmethod
    def _send(conn, payload):
        try:
            conn.sendall(payload)
            return True
        except OSError:
            return False

    def _log(self, addr, method, target, status, elapsed_ms):
        if self.access_log is None:
            return
        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        host = addr[0] if addr else "-"
        try:
            self.access_log.write(
                '%s %s "%s %s" %d %.2fms\n'
                % (stamp, host, method, target, status, elapsed_ms))
            self.access_log.flush()
        except Exception:
            pass
