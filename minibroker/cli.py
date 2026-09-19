"""Command line interfaces.

* ``python3 -m minibroker`` starts the broker server.
* ``mb-cli`` (see the project-root script) is the interactive client.
"""

from __future__ import annotations

import argparse
import shlex
import sys
from typing import List, Optional

from .broker import BLOCK, DROP_OLDEST, ERROR
from .client import BrokerClient, BrokerShutdown, ServerError
from .server import BrokerServer


# ---------------------------------------------------------------------- #
# server
# ---------------------------------------------------------------------- #
def build_server(argv: Optional[List[str]] = None) -> BrokerServer:
    parser = argparse.ArgumentParser(prog="minibroker", description="minibroker server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7379)
    parser.add_argument("--aof", default=".broker.aof", help="AOF file path")
    parser.add_argument(
        "--retain",
        type=int,
        default=1000,
        help="retained messages per topic when no subscriber is present (0 = drop)",
    )
    parser.add_argument(
        "--max-command-size", type=int, default=1024 * 1024, help="bytes"
    )
    parser.add_argument(
        "--queue-size",
        type=int,
        default=10000,
        help="per-connection outgoing queue length",
    )
    parser.add_argument(
        "--overflow",
        choices=[DROP_OLDEST, ERROR, BLOCK],
        default=DROP_OLDEST,
        help="policy when a subscriber queue is full",
    )
    parser.add_argument(
        "--block-timeout",
        type=float,
        default=30.0,
        help="max seconds a PUBLISH may block under the 'block' policy",
    )
    parser.add_argument(
        "--fsync", action="store_true", help="fsync the AOF after every write"
    )
    args = parser.parse_args(argv)

    server = BrokerServer(
        host=args.host,
        port=args.port,
        aof_path=args.aof,
        retain=args.retain,
        max_command_size=args.max_command_size,
        queue_size=args.queue_size,
        overflow=args.overflow,
        block_timeout=args.block_timeout,
        fsync=args.fsync,
    )
    return server


def main(argv: Optional[List[str]] = None) -> int:
    server = build_server(argv)
    server.start()
    print(
        "minibroker listening on %s:%d (aof=%s, retain=%d, overflow=%s)"
        % (server.host, server.port, server.broker.aof_path,
           server.broker.retain, server.broker.overflow),
        file=sys.stderr,
    )
    try:
        server.broker.shutdown_event.wait()
    except KeyboardInterrupt:
        print("\nshutting down ...", file=sys.stderr)
    server.stop()
    return 0


# ---------------------------------------------------------------------- #
# interactive client (mb-cli)
# ---------------------------------------------------------------------- #
CLIENT_HELP = """\
commands:
  connect [host [port]]      open a connection (default 127.0.0.1:7379)
  ping                       server round-trip
  publish <topic> <payload>  publish a message (payload is the raw rest of line)
  subscribe <topic>          subscribe (supports '*' and 'prefix/*' wildcards)
  unsubscribe <topic>        unsubscribe
  stats                      print broker statistics
  flush                      clear retained messages and the AOF
  recv [timeout]             block until one pushed message is printed
  shutdown                   ask the broker to shut down
  disconnect / close         close the current connection
  help / quit
Any command issued while subscribed keeps running; pushed messages are printed
in real time as they arrive.
"""


def client_main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="mb-cli", description="minibroker client")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7379)
    parser.add_argument(
        "-c", "--command", action="append", default=[],
        help="run one non-interactive command (repeatable)",
    )
    args = parser.parse_args(argv)

    state = {"client": None}

    def ensure_connected() -> BrokerClient:
        if state["client"] is None:
            current = BrokerClient(args.host, args.port)
            current.connect()
            current.on_message = _print_message
            state["client"] = current
        return state["client"]

    def teardown() -> None:
        if state["client"] is not None:
            state["client"].close()
            state["client"] = None

    scripted = list(args.command)
    if scripted:
        try:
            for raw in scripted:
                stop = _run_line(raw, ensure_connected, state)
                if stop:
                    break
        finally:
            teardown()
        return 0

    print("mb-cli - interactive minibroker client. type 'help' for help.")
    try:
        while True:
            try:
                raw = input("mb> ")
            except EOFError:
                print()
                break
            stop = _run_line(raw, ensure_connected, state)
            if stop:
                break
    except KeyboardInterrupt:
        print()
    finally:
        teardown()
    return 0


def _print_message(topic: str, seq: int, payload: bytes) -> None:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        text = repr(payload)
    print("  << MSG seq=%d topic=%s payload=%s" % (seq, topic, text))


def _run_line(raw: str, connect, state=None) -> bool:
    """Execute one interactive line. Return True to quit."""
    line = raw.strip()
    if not line:
        return False
    if line in {"quit", "exit"}:
        return True
    if line == "help":
        print(CLIENT_HELP)
        return False

    parts = shlex.split(line, posix=True)
    cmd = parts[0].lower()

    if cmd == "connect":
        host = parts[1] if len(parts) > 1 else "127.0.0.1"
        port = int(parts[2]) if len(parts) > 2 else 7379
        if state["client"] is not None:
            state["client"].close()
        current = BrokerClient(host, port)
        current.connect()
        current.on_message = _print_message
        state["client"] = current
        print("connected to %s:%d" % (host, port))
        return False

    if cmd in {"disconnect", "close"}:
        if state["client"] is not None:
            state["client"].close()
            state["client"] = None
        print("disconnected")
        return False

    client = connect()
    try:
        if cmd == "ping":
            print("PONG" if client.ping() else "no pong")
        elif cmd == "publish":
            if len(parts) < 2:
                print("usage: publish <topic> <payload>")
            else:
                # payload is the raw remainder after the topic, spaces kept.
                topic = parts[1]
                payload = line.split(None, 2)[2].encode("utf-8") if len(parts) > 2 else b""
                seq = client.publish(topic, payload)
                print("published seq=%d" % seq)
        elif cmd == "subscribe":
            for topic in parts[1:]:
                client.subscribe(topic)
                print("subscribed to %s" % topic)
        elif cmd == "unsubscribe":
            for topic in parts[1:]:
                client.unsubscribe(topic)
                print("unsubscribed from %s" % topic)
        elif cmd == "stats":
            for key, value in client.stats().items():
                print("%s=%s" % (key, value))
        elif cmd == "flush":
            client.flush()
            print("flushed")
        elif cmd == "recv":
            timeout = float(parts[1]) if len(parts) > 1 else None
            msg = client.next_message(timeout=timeout)
            if msg is None:
                print("(no message within timeout)")
            else:
                _print_message(*msg)
        elif cmd == "shutdown":
            try:
                client.shutdown()
            except BrokerShutdown:
                pass
            print("shutdown requested")
            return True
        else:
            print("unknown command: %s (try 'help')" % cmd)
    except ServerError as exc:
        print("ERR %s" % exc)
    except BrokerShutdown:
        print("server closed the connection (shutdown)")
        return True
    except (OSError, ConnectionError) as exc:
        print("connection error: %s" % exc)
    return False
