"""TCP server: one reader thread plus one delivery thread per connection."""

import argparse
import itertools
import queue
import socket
import threading

from . import protocol
from .broker import Broker, BrokerError


class _ClientConn:
    __slots__ = ("sock", "send_lock")

    def __init__(self, sock):
        self.sock = sock
        self.send_lock = threading.Lock()


class BrokerServer:
    def __init__(self, host="127.0.0.1", port=7379, broker=None,
                 max_command=protocol.DEFAULT_MAX_COMMAND, **broker_options):
        self.host = host
        self.port = port
        self.broker = broker if broker is not None else Broker(**broker_options)
        self.max_command = max_command
        self._listener = None
        self._ready = threading.Event()
        self._stopping = threading.Event()
        self._serve_thread = None
        self._conn_ids = itertools.count(1)
        self._connections = {}
        self._connections_lock = threading.Lock()

    # -- lifecycle -------------------------------------------------------

    def start(self):
        """Start serving in a background thread; returns once listening."""
        self._serve_thread = threading.Thread(
            target=self.serve_forever, name="broker-accept", daemon=True
        )
        self._serve_thread.start()
        self._ready.wait()
        return self

    def serve_forever(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((self.host, self.port))
        listener.listen(128)
        listener.settimeout(0.2)
        self._listener = listener
        self.port = listener.getsockname()[1]
        self._ready.set()
        try:
            while not self._stopping.is_set():
                try:
                    client_sock, _ = listener.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                thread = threading.Thread(
                    target=self._handle_connection,
                    args=(client_sock,),
                    name="broker-conn",
                    daemon=True,
                )
                thread.start()
        finally:
            try:
                listener.close()
            except OSError:
                pass
            self._close_all_clients()
            self.broker.close()

    def stop(self):
        """Graceful shutdown: notify connected clients, then close."""
        self._stopping.set()
        listener = self._listener
        if listener is not None:
            try:
                listener.close()
            except OSError:
                pass

    def wait(self, timeout=None):
        if self._serve_thread is not None:
            self._serve_thread.join(timeout)

    def _close_all_clients(self):
        with self._connections_lock:
            clients = list(self._connections.values())
        for client in clients:
            try:
                self._send(client, protocol.encode_command(
                    "+BYE", ["server", "shutting", "down"]))
            except OSError:
                pass
            try:
                client.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                client.sock.close()
            except OSError:
                pass

    # -- per-connection handling ----------------------------------------

    def _handle_connection(self, sock):
        conn_id = next(self._conn_ids)
        client = _ClientConn(sock)
        with self._connections_lock:
            self._connections[conn_id] = client
        delivery_queue = self.broker.register_connection(conn_id)
        stop_writer = threading.Event()
        writer = threading.Thread(
            target=self._writer,
            args=(delivery_queue, client, stop_writer),
            name="broker-writer",
            daemon=True,
        )
        writer.start()
        try:
            stream = sock.makefile("rb")
            while not self._stopping.is_set():
                try:
                    tokens, payload = protocol.read_frame(
                        stream, self.max_command)
                except EOFError:
                    break
                except protocol.ProtocolError as exc:
                    # Frame-level corruption: report, then drop the
                    # connection because the stream cannot be resynced.
                    try:
                        self._send(client, protocol.encode_error(str(exc)))
                    except OSError:
                        pass
                    break
                self._dispatch(conn_id, client, tokens, payload)
        finally:
            stop_writer.set()
            self.broker.deregister_connection(conn_id)
            with self._connections_lock:
                self._connections.pop(conn_id, None)
            try:
                sock.close()
            except OSError:
                pass

    def _writer(self, delivery_queue, client, stop_writer):
        while not stop_writer.is_set() and not self._stopping.is_set():
            try:
                seq, topic, payload = delivery_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self._send(client, protocol.encode_message(seq, topic, payload))
            except OSError:
                break

    @staticmethod
    def _send(client, data):
        with client.send_lock:
            client.sock.sendall(data)

    # -- command dispatch -------------------------------------------------

    def _dispatch(self, conn_id, client, tokens, payload):
        command = tokens[0].upper()
        try:
            if command == "PING" and len(tokens) == 1:
                reply = b"+PONG\n"
            elif command == "PUBLISH" and len(tokens) == 3 and payload is not None:
                seq = self.broker.publish(tokens[1], payload)
                reply = protocol.encode_ok(seq)
            elif command == "SUBSCRIBE" and len(tokens) == 2:
                self.broker.subscribe(conn_id, tokens[1])
                reply = protocol.encode_ok()
            elif command == "UNSUBSCRIBE" and len(tokens) == 2:
                self.broker.unsubscribe(conn_id, tokens[1])
                reply = protocol.encode_ok()
            elif command == "STATS" and len(tokens) == 1:
                stats = self.broker.stats()
                body = " ".join("%s=%s" % item for item in stats.items())
                reply = ("+STATS " + body + "\n").encode("utf-8")
            elif command == "FLUSH" and len(tokens) == 1:
                self.broker.flush()
                reply = protocol.encode_ok()
            elif command == "SHUTDOWN" and len(tokens) == 1:
                self._send(client, protocol.encode_ok())
                threading.Thread(target=self.stop, daemon=True).start()
                return
            else:
                reply = protocol.encode_error(
                    "unknown or malformed command: %s" % tokens[0])
        except BrokerError as exc:
            reply = protocol.encode_error(str(exc))
        try:
            self._send(client, reply)
        except OSError:
            pass


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="mb-server", description="minibroker pub/sub server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7379)
    parser.add_argument("--retention", type=int, default=1000,
                        help="messages kept per topic (0 = drop when no "
                             "subscriber consumes them)")
    parser.add_argument("--max-queue", type=int, default=10000,
                        help="per-subscriber delivery queue limit")
    parser.add_argument("--full-policy", choices=["error", "block"],
                        default="error",
                        help="PUBLISH behaviour when a subscriber queue "
                             "is full")
    parser.add_argument("--aof", default=".broker.aof",
                        help="append-only file path ('' disables)")
    parser.add_argument("--max-command", type=int,
                        default=protocol.DEFAULT_MAX_COMMAND,
                        help="maximum command size in bytes")
    args = parser.parse_args(argv)

    server = BrokerServer(
        host=args.host,
        port=args.port,
        max_command=args.max_command,
        retention=args.retention,
        max_queue=args.max_queue,
        full_policy=args.full_policy,
        aof_path=args.aof or None,
    )
    print("minibroker listening on %s:%d (aof=%s)"
          % (args.host, args.port, args.aof or "disabled"))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.stop()
        server.wait()
    print("minibroker stopped")


if __name__ == "__main__":
    main()
