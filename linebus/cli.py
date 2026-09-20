"""Command-line client for linebus."""

from __future__ import annotations

import argparse
import shlex
import sys
import threading
from typing import Optional

from .client import LinebusClient, LinebusConnectionError, LinebusError, LinebusTimeout


HELP = """\
commands:
  ping
  publish <topic> <payload>
  subscribe <topic> [topic...]
  unsubscribe <topic>
  stats
  flush
  shutdown
  quit/exit

While subscribed in the CLI, incoming events are printed as:
EVENT <seq> <topic> <payload-length> <repr(payload)>
"""


class InteractiveCLI:
    def __init__(self, client: LinebusClient, *, stream=None):
        self.client = client
        self.stream = stream or sys.stdout
        self.subscriptions: set[str] = set()
        self._stop_printer = threading.Event()
        self._printer: Optional[threading.Thread] = None

    def start_printer(self) -> None:
        if self._printer is not None:
            return
        self._stop_printer.clear()
        self._printer = threading.Thread(target=self._print_loop, daemon=True)
        self._printer.start()

    def stop_printer(self) -> None:
        self._stop_printer.set()
        if self._printer is not None:
            self._printer.join(timeout=0.2)
        self._printer = None

    def _print_loop(self) -> None:
        while not self._stop_printer.is_set():
            try:
                event = self.client.next_message(timeout=0.2)
            except LinebusTimeout:
                continue
            except LinebusConnectionError as exc:
                print(f"connection closed: {exc}", file=self.stream)
                return
            if event is None:
                return
            print(
                f"EVENT {event.sequence} {event.topic} {len(event.payload)} {event.payload!r}",
                file=self.stream,
                flush=True,
            )

    def run_one(self, text: str) -> bool:
        try:
            argv = shlex.split(text)
        except ValueError as exc:
            print(f"ERR {exc}", file=self.stream)
            return True
        if not argv:
            return True
        command = argv[0].lower()
        if command in {"quit", "exit"}:
            return False
        if command == "help":
            print(HELP, file=self.stream)
            return True
        try:
            if command == "ping":
                print(self.client.ping(), file=self.stream)
            elif command == "publish":
                if len(argv) < 2:
                    raise LinebusError("usage: publish <topic> <payload>")
                topic = argv[1]
                payload = " ".join(argv[2:]).encode("utf-8")
                sequence = self.client.publish(topic, payload)
                print(f"OK SEQ {sequence}", file=self.stream)
            elif command == "subscribe":
                if len(argv) < 2:
                    raise LinebusError("usage: subscribe <topic> [topic...]")
                self.start_printer()
                for topic in argv[1:]:
                    self.client.subscribe(topic)
                    self.subscriptions.add(topic)
                    print(f"OK SUBSCRIBED {topic}", file=self.stream, flush=True)
            elif command == "unsubscribe":
                if len(argv) != 2:
                    raise LinebusError("usage: unsubscribe <topic>")
                topic = argv[1]
                self.client.unsubscribe(topic)
                self.subscriptions.discard(topic)
                print(f"OK UNSUBSCRIBED {topic}", file=self.stream)
            elif command == "stats":
                print(self.client.stats(), file=self.stream)
            elif command == "flush":
                self.client.flush()
                print("OK FLUSHED", file=self.stream)
            elif command == "shutdown":
                print("OK SHUTDOWN", file=self.stream)
                self.client.shutdown()
                return False
            else:
                print(f"ERR unknown command: {command}", file=self.stream)
        except LinebusError as exc:
            print(str(exc), file=self.stream)
        return True

    def interact(self) -> int:
        self.start_printer()
        print("linebus cli; type 'help' for commands", file=self.stream)
        try:
            while True:
                try:
                    line = input("lb> ")
                except EOFError:
                    break
                except KeyboardInterrupt:
                    print()
                    break
                if not self.run_one(line):
                    break
        finally:
            self.stop_printer()
        return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lb-cli", description="Command-line linebus client")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7379)
    parser.add_argument("--timeout", type=float, default=5.0)
    sub = parser.add_subparsers(dest="action")
    sub.add_parser("ping")
    p = sub.add_parser("publish")
    p.add_argument("topic")
    p.add_argument("payload", nargs="?", default="")
    s = sub.add_parser("subscribe")
    s.add_argument("topics", nargs="+")
    sub.add_parser("stats")
    sub.add_parser("interactive")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    with LinebusClient(args.host, args.port, timeout=args.timeout) as client:
        if args.action == "ping":
            print(client.ping())
        elif args.action == "publish":
            print(f"OK SEQ {client.publish(args.topic, args.payload.encode('utf-8'))}")
        elif args.action == "stats":
            print(client.stats())
        elif args.action == "subscribe":
            cli = InteractiveCLI(client)
            for topic in args.topics:
                client.subscribe(topic)
                print(f"OK SUBSCRIBED {topic}", flush=True)
            cli.start_printer()
            try:
                while True:
                    threading.Event().wait(3600)
            except KeyboardInterrupt:
                pass
            cli.stop_printer()
        else:
            return InteractiveCLI(client).interact()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
