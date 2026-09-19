"""Multi-threaded TCP server (thread-pool per connection) and shutdown."""

import socket
import threading
from concurrent.futures import ThreadPoolExecutor

from .app import MiniWeb
from .config import Config


class HttpServer:
    def __init__(
        self,
        app: MiniWeb,
        config: Config,
        logger=None,
    ) -> None:
        self.app = app
        self.config = config
        if logger is not None:
            self.app.logger = logger
        self._sock: socket.socket = None
        self._pool: ThreadPoolExecutor = None
        self._futures = set()
        self._connections = set()
        self._conn_lock = threading.Lock()
        self._running = threading.Event()

    @property
    def address(self):
        if self._sock is None:
            return None
        return self._sock.getsockname()[:2]

    def listen(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.config.host, self.config.port))
        sock.listen(128)
        # Honour idle timeouts at the socket level.
        sock.settimeout(0.5)
        self._sock = sock
        self._pool = ThreadPoolExecutor(
            max_workers=max(1, self.config.workers),
            thread_name_prefix="miniweb-worker",
        )
        self._running.set()

    def serve_forever(self) -> None:
        if self._sock is None:
            self.listen()
        while self._running.is_set():
            try:
                conn, addr = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            future = self._pool.submit(self._serve, conn, addr)
            self._futures.add(future)
            future.add_done_callback(self._futures.discard)

    def _serve(self, conn: socket.socket, addr) -> None:
        conn.settimeout(self.config.timeout)
        with self._conn_lock:
            self._connections.add(conn)
        reader = conn.makefile("rb")
        writer = conn.makefile("wb")
        try:
            self.app.handle_connection(
                reader, writer, addr, self.config, sock=conn
            )
        finally:
            with self._conn_lock:
                self._connections.discard(conn)
            for obj in (writer, reader, conn):
                try:
                    obj.close()
                except Exception:
                    pass

    def start_in_thread(self) -> threading.Thread:
        if self._sock is None:
            self.listen()
        thread = threading.Thread(target=self.serve_forever, name="miniweb-accept")
        thread.daemon = True
        thread.start()
        return thread

    def shutdown(self, wait: bool = True) -> None:
        """Stop accepting and close the listening socket / pool."""
        self._running.clear()
        sock = self._sock
        self._sock = None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        # Close every keep-alive connection still open so worker threads
        # blocked on socket reads wake up and finish promptly.
        with self._conn_lock:
            connections = list(self._connections)
            self._connections.clear()
        for conn in connections:
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                conn.close()
            except OSError:
                pass
        pool = self._pool
        if pool is not None:
            # Worker threads are daemonic inside the pool; cancel queued
            # work and shut down without blocking on in-flight requests.
            pool.shutdown(wait=wait, cancel_futures=True)
