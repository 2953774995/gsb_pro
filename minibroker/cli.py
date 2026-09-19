"""mb-cli: interactive minibroker client."""

import argparse
import threading
import time

from .client import BrokerClient, BrokerServerError

HELP = """\
commands:
  publish <topic> <message...>   publish a message
  subscribe <pattern>            subscribe (supports <topic>/* wildcards)
  unsubscribe <pattern>          unsubscribe
  listen                         block and print messages until Ctrl-C
  ping                           check the broker is alive
  stats                          show broker statistics
  flush                          clear all retained messages
  shutdown                       ask the broker to shut down
  quit                           disconnect and exit
"""


def _printer(client, stop):
    while not stop.is_set():
        message = client.next_message(timeout=0.2)
        if message is None:
            continue
        seq, topic, payload = message
        print("\r[%d] %s: %r" % (seq, topic, payload), flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="mb-cli", description="interactive minibroker client")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7379)
    args = parser.parse_args(argv)

    client = BrokerClient(host=args.host, port=args.port)
    try:
        client.connect()
    except OSError as exc:
        print("cannot connect to %s:%d: %s" % (args.host, args.port, exc))
        return 1
    print("connected to %s:%d - type 'help' for commands"
          % (args.host, args.port))

    stop = threading.Event()
    printer = threading.Thread(target=_printer, args=(client, stop),
                               daemon=True)
    printer.start()

    try:
        while True:
            try:
                line = input("mb> ")
            except EOFError:
                break
            parts = line.strip().split()
            if not parts:
                continue
            command, rest = parts[0].lower(), parts[1:]
            try:
                if command in ("quit", "exit"):
                    break
                elif command == "help":
                    print(HELP)
                elif command == "publish" and len(rest) >= 2:
                    seq = client.publish(rest[0], " ".join(rest[1:]))
                    print("published seq=%d" % seq)
                elif command == "subscribe" and len(rest) == 1:
                    client.subscribe(rest[0])
                    print("subscribed to %s" % rest[0])
                elif command == "unsubscribe" and len(rest) == 1:
                    client.unsubscribe(rest[0])
                    print("unsubscribed from %s" % rest[0])
                elif command == "listen":
                    print("listening... (Ctrl-C to stop)")
                    try:
                        while True:
                            time.sleep(1)
                    except KeyboardInterrupt:
                        print()
                elif command == "ping":
                    print("PONG" if client.ping() else "no reply")
                elif command == "stats":
                    print(client.stats())
                elif command == "flush":
                    client.flush()
                    print("flushed")
                elif command == "shutdown":
                    client.shutdown()
                    print("broker shutting down")
                    break
                else:
                    print("unknown command - type 'help'")
            except BrokerServerError as exc:
                print("ERR %s" % exc)
            except (ConnectionError, OSError) as exc:
                print("connection lost: %s" % exc)
                break
    except KeyboardInterrupt:
        print()
    finally:
        stop.set()
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
