"""Interactive command line client ``mb-cli``.

Usage::

    python3 -m minibroker.cli [--host HOST] [--port PORT]

Once connected, messages pushed to subscribed topics arrive live while you
type.  Type ``help`` inside the REPL for the command list.
"""

from __future__ import annotations

import argparse
import json
import shlex
import threading

from .client import BrokerClient, BrokerClosed, BrokerError

HELP = """\
commands:
  publish <topic> <message...>   publish a message (rest of line is the payload)
  subscribe <pattern>            subscribe to a topic or wildcard (e.g. news/*)
  unsubscribe <pattern>          unsubscribe
  ping                           check the connection
  stats                          show broker statistics
  flush                          clear all retained messages and the AOF
  shutdown                       ask the broker to shut down gracefully
  help                           show this help
  quit                           disconnect and exit
Incoming messages are printed live as they arrive.
"""


def _format_message(msg) -> str:
    try:
        text = msg.payload.decode("utf-8")
    except UnicodeDecodeError:
        text = repr(msg.payload)
    return "[msg #%d] %s: %s" % (msg.seq, msg.topic, text)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="mb-cli", description="minibroker interactive client")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7379)
    args = parser.parse_args(argv)

    client = BrokerClient(args.host, args.port)
    try:
        client.connect()
    except OSError as exc:
        print("mb-cli: cannot connect to %s:%d: %s" % (args.host, args.port, exc))
        return 1

    stop = threading.Event()

    def printer():
        while not stop.is_set():
            try:
                msg = client.next_message(timeout=0.2)
            except BrokerClosed:
                if not stop.is_set():
                    print("\n[disconnected from broker]")
                return
            if msg is not None:
                print("\r%s\nmb> " % _format_message(msg), end="", flush=True)

    threading.Thread(target=printer, daemon=True).start()
    print("connected to %s:%d -- type 'help' for commands" % (args.host, args.port))

    try:
        while True:
            try:
                line = input("mb> ")
            except (EOFError, KeyboardInterrupt):
                print()
                break
            line = line.strip()
            if not line:
                continue
            try:
                tokens = shlex.split(line)
            except ValueError:
                tokens = line.split()
            cmd, rest = tokens[0].lower(), tokens[1:]
            try:
                if cmd == "publish":
                    if len(rest) < 2:
                        print("usage: publish <topic> <message...>")
                        continue
                    topic = rest[0]
                    payload = line.split(None, 2)[2]  # everything after the topic
                    seq = client.publish(topic, payload)
                    print("ok (seq=%d)" % seq)
                elif cmd == "subscribe":
                    client.subscribe(rest[0])
                    print("subscribed to %s" % rest[0])
                elif cmd == "unsubscribe":
                    client.unsubscribe(rest[0])
                    print("unsubscribed from %s" % rest[0])
                elif cmd == "ping":
                    print("PONG" if client.ping() else "?")
                elif cmd == "stats":
                    print(json.dumps(client.stats(), indent=2, sort_keys=True))
                elif cmd == "flush":
                    client.flush()
                    print("flushed")
                elif cmd == "shutdown":
                    client.shutdown()
                    print("shutdown requested")
                elif cmd == "help":
                    print(HELP)
                elif cmd in ("quit", "exit"):
                    break
                else:
                    print("unknown command %r -- type 'help'" % cmd)
            except IndexError:
                print("missing argument -- type 'help'")
            except BrokerError as exc:
                print("ERR %s" % exc)
            except BrokerClosed as exc:
                print("connection closed: %s" % exc)
                break
    finally:
        stop.set()
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
