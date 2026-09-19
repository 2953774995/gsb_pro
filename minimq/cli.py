"""minimq-cli: command line interface over an on-disk minimq broker.

Examples::

    python3 -m minimq --data-dir ./data create-topic orders
    python3 -m minimq --data-dir ./data produce orders "hello world"
    python3 -m minimq --data-dir ./data consume orders --group g1 --max 10 --ack
    python3 -m minimq --data-dir ./data topics
    python3 -m minimq --data-dir ./data groups

State (message logs + consumer-group offsets) lives entirely in the
``--data-dir`` directory, so a later invocation (a "reconnect") resumes
exactly where the previous one stopped.
"""

import argparse
import sys
import time

from .broker import Broker
from .errors import MqError


def _build_parser():
    parser = argparse.ArgumentParser(
        prog="minimq",
        description="A tiny in-memory message queue with disk persistence.",
    )
    parser.add_argument(
        "--data-dir",
        default="minimq-data",
        help="directory holding logs and consumer offsets (default: ./minimq-data)",
    )
    parser.add_argument(
        "--no-fsync",
        action="store_true",
        help="skip fsync on writes (faster, less durable - tests/demos only)",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    p_create = sub.add_parser("create-topic", help="create a topic")
    p_create.add_argument("topic")
    p_create.add_argument("--max-messages", type=int, default=None,
                          help="retain at most N messages (oldest dropped first)")
    p_create.add_argument("--max-bytes", type=int, default=None,
                          help="retain at most N payload bytes")
    p_create.add_argument("--max-message-size", type=int, default=None,
                          help="reject publishes larger than this many bytes")
    p_create.set_defaults(func=cmd_create_topic)

    p_del = sub.add_parser("delete-topic", help="delete a topic and its state")
    p_del.add_argument("topic")
    p_del.set_defaults(func=cmd_delete_topic)

    p_topics = sub.add_parser("topics", help="list topics and their offsets")
    p_topics.set_defaults(func=cmd_topics)

    p_groups = sub.add_parser("groups", help="list consumer groups")
    p_groups.add_argument("--topic", default=None)
    p_groups.set_defaults(func=cmd_groups)

    p_prod = sub.add_parser("produce", help="publish a message")
    p_prod.add_argument("topic")
    p_prod.add_argument("message", nargs="?", default=None,
                        help="message text; reads stdin if omitted")
    p_prod.set_defaults(func=cmd_produce)

    p_cons = sub.add_parser("consume", help="poll and print messages")
    p_cons.add_argument("topic")
    p_cons.add_argument("--group", required=True, help="consumer group name")
    p_cons.add_argument("--max", dest="max_messages", type=int, default=1,
                        help="maximum messages to pull (default 1)")
    p_cons.add_argument("--ack", action="store_true",
                        help="acknowledge every printed message")
    p_cons.add_argument("--wait", type=float, default=0.0,
                        help="seconds to keep polling while no messages are "
                             "available (default 0 = one poll only)")
    p_cons.set_defaults(func=cmd_consume)

    return parser


def cmd_create_topic(args, broker):
    broker.create_topic(
        args.topic,
        max_messages=args.max_messages,
        max_bytes=args.max_bytes,
        max_message_size=args.max_message_size,
    )
    print("created topic {!r}".format(args.topic))


def cmd_delete_topic(args, broker):
    broker.delete_topic(args.topic)
    print("deleted topic {!r}".format(args.topic))


def cmd_topics(args, broker):
    infos = broker.topic_info()
    if not infos:
        print("(no topics)")
        return
    header = "{:<20} {:>8} {:>8} {:>8} {:>10}  {}".format(
        "TOPIC", "BEGIN", "END", "NEXT", "MSGS", "BYTES  RETENTION"
    )
    print(header)
    for name, info in infos.items():
        ret = info["retention"]
        ret_parts = []
        if ret["max_messages"] is not None:
            ret_parts.append("max_messages={}".format(ret["max_messages"]))
        if ret["max_bytes"] is not None:
            ret_parts.append("max_bytes={}".format(ret["max_bytes"]))
        ret_s = ",".join(ret_parts) or "-"
        print("{:<20} {:>8} {:>8} {:>8} {:>10} {:>6}  {}".format(
            name,
            info["earliest_offset"],
            info["latest_offset"],
            info["next_offset"],
            info["message_count"],
            info["size_bytes"],
            ret_s,
        ))


def cmd_groups(args, broker):
    groups = broker.list_groups(args.topic)
    if not groups:
        print("(no consumer groups)")
        return
    for topic, group in groups:
        try:
            hwm, gaps = broker.group_progress(topic, group)
            gap_s = ",".join(str(g) for g in gaps) or "-"
            print("{}\t{}\thwm={}\tgaps={}".format(topic, group, hwm, gap_s))
        except MqError:
            print("{}\t{}\t(state only)".format(topic, group))


def cmd_produce(args, broker):
    if args.message is None:
        message = sys.stdin.read()
        if message.endswith("\n"):
            message = message[:-1]
    else:
        message = args.message
    offset = broker.publish(args.topic, message)
    print(offset)


def cmd_consume(args, broker):
    consumer = broker.subscribe(args.topic, args.group)
    try:
        deadline = time.monotonic() + args.wait
        while True:
            messages = consumer.poll(args.max_messages)
            if messages:
                for msg in messages:
                    text = msg.value.decode("utf-8", errors="replace")
                    print("{}\t{}".format(msg.offset, text))
                    if args.ack:
                        consumer.ack(msg.offset)
                return 0
            if time.monotonic() >= deadline:
                return 0
            time.sleep(0.05)
    finally:
        consumer.close()


def main(argv=None):
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        with Broker(args.data_dir, fsync=not args.no_fsync) as broker:
            result = args.func(args, broker)
        return result or 0
    except MqError as exc:
        print("error: {}".format(exc), file=sys.stderr)
        return 2
    except BrokenPipeError:
        return 0


if __name__ == "__main__":
    sys.exit(main())
