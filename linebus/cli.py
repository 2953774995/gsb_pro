"""``lb-cli`` interactive command line client."""

from __future__ import annotations

import argparse
import queue
import sys
import threading
from typing import List, Optional, TextIO

from .client import LinebusClient, LinebusDisconnected, LinebusError


HELP = """\
commands:
  help                         show this help
  ping                         send PING
  publish <topic> <text>       publish UTF-8 text (use the SDK for raw bytes)
  subscribe <topic>            subscribe and enter realtime event mode
  unsubscribe <topic>          cancel a subscription
  stats                        print server statistics
  flush                        flush memory and AOF
  shutdown                     gracefully stop the server
  quit / exit                  close this client
"""


class EventPrinter:
    def __init__(self, client: LinebusClient, output: TextIO) -> None:
        self.client = client
        self.output = output
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                message = self.client.next_message(timeout=0.1)
            except queue.Empty:
                continue
            except LinebusDisconnected:
                print("(disconnected from server)", file=self.output, flush=True)
                self.stop_event.set()
                break
            except LinebusError as exc:
                print(f"(error: {exc})", file=self.output, flush=True)
                continue
            print(
                f"EVENT seq={message.sequence} topic={message.topic} "
                f"len={len(message.payload)} payload={message.payload!r}",
                file=self.output,
                flush=True,
            )

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=1.0)


def _interactive_subscribe(client: LinebusClient, topic: str, output: TextIO) -> None:
    client.subscribe(topic)
    print(f"subscribed to {topic}; press Enter or type quit to leave event mode", flush=True)
    printer = EventPrinter(client, output)
    printer.start()
    try:
        while not printer.stop_event.is_set():
            line = sys.stdin.readline()
            if not line:
                break
            command = line.strip().lower()
            if command in {"quit", "exit", ""}:
                break
            if command == "unsubscribe":
                print("usage: unsubscribe <topic>", flush=True)
                continue
            if command.startswith("unsubscribe "):
                target = command.split(" ", 1)[1].strip()
                try:
                    client.unsubscribe(target)
                    if target == topic:
                        break
                except LinebusError as exc:
                    print(f"ERR {exc}", flush=True)
                continue
            print("event mode supports: unsubscribe <topic>, quit/exit (or press Enter)", flush=True)
    finally:
        printer.stop()


def run_repl(client: LinebusClient, input_stream: TextIO = sys.stdin, output: TextIO = sys.stdout) -> int:
    print("linebus CLI - type 'help' for commands", file=output, flush=True)
    while True:
        try:
            print("linebus> ", end="", file=output, flush=True)
            line = input_stream.readline()
        except KeyboardInterrupt:
            print(file=output)
            break
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        parts = line.split(" ", 2)
        command = parts[0].lower()
        try:
            if command in {"quit", "exit"}:
                break
            elif command == "help":
                print(HELP, file=output, end="")
            elif command == "ping":
                print(client.ping(), file=output)
            elif command == "subscribe" and len(parts) == 2:
                _interactive_subscribe(client, parts[1], output)
            elif command == "unsubscribe" and len(parts) == 2:
                client.unsubscribe(parts[1])
                print("UNSUBSCRIBED", file=output)
            elif command == "publish" and len(parts) == 3:
                sequence = client.publish(parts[1], parts[2].encode("utf-8"))
                print(f"PUBLISHED {sequence}", file=output)
            elif command == "stats":
                stats = client.stats()
                print(" ".join(f"{key}={value}" for key, value in stats.items()), file=output)
            elif command == "flush":
                client.flush()
                print("FLUSHED", file=output)
            elif command == "shutdown":
                client.shutdown()
                print("SHUTDOWN", file=output)
                break
            else:
                print("ERR unknown or malformed command; type help", file=output)
        except LinebusError as exc:
            print(f"ERR {exc}", file=output)
        except KeyboardInterrupt:
            print(file=output)
            break
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Interactive Linebus client")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7379)
    parser.add_argument("--connect-timeout", type=float, default=10.0)
    parser.add_argument(
        "command",
        nargs="?",
        choices=("shell",),
        default="shell",
        help=argparse.SUPPRESS,
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    client = LinebusClient(args.host, args.port, connect_timeout=args.connect_timeout)
    try:
        client.connect()
        return run_repl(client)
    except (OSError, LinebusError) as exc:
        print(f"ERR {exc}", file=sys.stderr)
        return 1
    finally:
        client.close()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
