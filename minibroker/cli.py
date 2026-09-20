"""mb-cli: a tiny standard-library command line client."""

from __future__ import annotations

import argparse
import shlex
import sys
from typing import List, Optional

from .client import BrokerClient, ClientError, Message, ServerError


HELP_TEXT = """commands:
  ping
  publish <topic> <payload>      payload is one shell-like token; use quotes
  subscribe <topic>             enter subscription/live-print mode
  unsubscribe <topic>
  stats
  flush
  shutdown
  help
  quit/exit

While subscribed, incoming messages are printed continuously.  Press Ctrl-C to
leave live mode and return to the command prompt.
"""


def _to_text(value: bytes) -> str:
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError:
        return repr(value)


def _print_message(message: Message) -> None:
    print(f"[PUB #{message.sequence}] {_to_text(message.topic)}: {_to_text(message.payload)}")
    sys.stdout.flush()


def _parse_command(line: str) -> List[str]:
    # shlex keeps spaces/tabs inside quoted payloads.  Binary content is not a
    # CLI goal; use the SDK for arbitrary bytes.
    return shlex.split(line, posix=True)


def run_cli(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="mb-cli", description="Interactive minibroker client")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7379)
    args = parser.parse_args(argv)

    client = BrokerClient(args.host, args.port, on_event=lambda event: print(f"<{event.upper()}>"))
    try:
        client.connect()
    except (OSError, ClientError) as exc:
        print(f"failed to connect: {exc}", file=sys.stderr)
        return 1

    print(f"connected to {args.host}:{args.port}; type 'help' for commands")
    try:
        while True:
            try:
                line = input("mb> ").strip()
            except EOFError:
                print()
                break
            except KeyboardInterrupt:
                print()
                break
            if not line:
                continue

            try:
                command_parts = _parse_command(line)
            except ValueError as exc:
                print(f"ERR parse error: {exc}", file=sys.stderr)
                continue
            command = command_parts[0].lower()

            try:
                if command in {"quit", "exit"}:
                    break
                elif command == "help":
                    print(HELP_TEXT)
                elif command == "ping":
                    client.ping()
                    print("PONG")
                elif command == "publish":
                    if len(command_parts) != 3:
                        print("usage: publish <topic> <payload>", file=sys.stderr)
                    else:
                        seq = client.publish(command_parts[1], command_parts[2])
                        print(f"OK {seq}")
                elif command == "subscribe":
                    if len(command_parts) != 2:
                        print("usage: subscribe <topic>", file=sys.stderr)
                        continue
                    client.subscribe(command_parts[1])
                    print(f"SUBSCRIBED {command_parts[1]}; waiting (Ctrl-C to stop)")
                    try:
                        while True:
                            try:
                                _print_message(client.next_message(1))
                            except TimeoutError:
                                continue
                    except KeyboardInterrupt:
                        print()
                        print("left live mode")
                elif command == "unsubscribe":
                    if len(command_parts) != 2:
                        print("usage: unsubscribe <topic>", file=sys.stderr)
                    else:
                        removed = client.unsubscribe(command_parts[1])
                        print("UNSUBSCRIBED" if removed else "NOT_SUBSCRIBED")
                elif command == "stats":
                    for key, value in client.stats().items():
                        print(f"{key}: {value}")
                elif command == "flush":
                    client.flush()
                    print("FLUSHED")
                elif command == "shutdown":
                    client.shutdown()
                    print("BYE")
                    break
                else:
                    print(f"ERR unknown command '{command}'", file=sys.stderr)
            except ServerError as exc:
                print(f"ERR {exc}", file=sys.stderr)
            except (ClientError, TimeoutError, OSError) as exc:
                print(f"ERR client failure: {exc}", file=sys.stderr)
    finally:
        client.close()
    return 0


def main() -> int:
    return run_cli()


if __name__ == "__main__":
    raise SystemExit(main())
