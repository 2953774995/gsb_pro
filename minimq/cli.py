"""minimq-cli: command line interface for minimq.

Usage examples::

    minimq-cli --data-dir ./mqdata create mytopic --max-messages 1000
    minimq-cli --data-dir ./mqdata produce mytopic "hello world"
    minimq-cli --data-dir ./mqdata consume mytopic -g workers -n 10
    minimq-cli --data-dir ./mqdata topics
"""

import argparse
import os
import sys

from .broker import Broker
from .errors import MqError

DEFAULT_DATA_DIR = os.environ.get("MINIMQ_DATA_DIR", "./minimq-data")


def build_parser():
    parser = argparse.ArgumentParser(
        prog="minimq-cli",
        description="Mini in-memory message queue with disk persistence.")
    parser.add_argument("--data-dir", default=DEFAULT_DATA_DIR,
                        help="state directory (default: %(default)s, "
                             "or $MINIMQ_DATA_DIR)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("create", help="create a topic")
    p.add_argument("topic")
    p.add_argument("--max-messages", type=int, default=None,
                   help="retention: keep at most N messages")
    p.add_argument("--max-bytes", type=int, default=None,
                   help="retention: keep at most N bytes of messages")

    p = sub.add_parser("produce", help="publish one message")
    p.add_argument("topic")
    p.add_argument("message")
    p.add_argument("--create", action="store_true",
                   help="create the topic if it does not exist")

    p = sub.add_parser("consume", help="poll and print messages")
    p.add_argument("topic")
    p.add_argument("-g", "--group", default="default",
                   help="consumer group (default: %(default)s)")
    p.add_argument("-n", "--num", type=int, default=1,
                   help="max messages to fetch (default: %(default)s)")
    p.add_argument("--no-ack", action="store_true",
                   help="do not acknowledge consumed messages "
                        "(they will be redelivered later)")

    sub.add_parser("topics", help="list topics and offsets")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    broker = Broker(data_dir=args.data_dir)
    try:
        if args.command == "create":
            broker.create_topic(args.topic, max_messages=args.max_messages,
                                max_bytes=args.max_bytes)
            print("created topic %r" % args.topic)
        elif args.command == "produce":
            if args.create and all(t["name"] != args.topic
                                   for t in broker.list_topics()):
                broker.create_topic(args.topic)
            offset = broker.publish(args.topic, args.message)
            print("published to %r at offset %d" % (args.topic, offset))
        elif args.command == "consume":
            consumer = broker.subscribe(args.topic, args.group)
            messages = consumer.poll(args.num)
            for msg in messages:
                print("%s:%d\t%s" % (msg.topic, msg.offset, msg.body))
                if not args.no_ack:
                    consumer.ack(msg.offset)
            if not messages:
                print("(no messages)", file=sys.stderr)
            consumer.close()
        elif args.command == "topics":
            infos = broker.list_topics()
            if not infos:
                print("(no topics)")
            for info in infos:
                retention = []
                if info["max_messages"] is not None:
                    retention.append("max_messages=%d" % info["max_messages"])
                if info["max_bytes"] is not None:
                    retention.append("max_bytes=%d" % info["max_bytes"])
                suffix = (" [" + ", ".join(retention) + "]") if retention else ""
                print("%s: base_offset=%d next_offset=%d stored=%d%s" % (
                    info["name"], info["base_offset"], info["next_offset"],
                    info["messages"], suffix))
        return 0
    except MqError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1
    finally:
        broker.close()


if __name__ == "__main__":
    sys.exit(main())
