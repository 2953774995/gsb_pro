"""Command line entry point."""

import argparse
import logging
import sys

from .app import Application
from .constants import (
    DEFAULT_BODY_LIMIT,
    DEFAULT_CONFIG_PATH,
    DEFAULT_HEADER_LIMIT,
    DEFAULT_HOST,
    DEFAULT_IDLE_TIMEOUT,
    DEFAULT_PORT,
    DEFAULT_ROOT,
    DEFAULT_WORKERS,
)
from .server import HTTPServer


def positive_int(value, name, minimum=1):
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{name} must be an integer") from exc
    if parsed < minimum:
        raise argparse.ArgumentTypeError(f"{name} must be >= {minimum}")
    return parsed


def build_parser():
    parser = argparse.ArgumentParser(
        prog="gwadmin",
        description="Factory edge gateway local management agent.",
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="listen address")
    parser.add_argument("--port", type=lambda v: positive_int(v, "port"), default=DEFAULT_PORT)
    parser.add_argument("--root", default=DEFAULT_ROOT, help="static web asset directory")
    parser.add_argument(
        "--workers",
        type=lambda v: positive_int(v, "workers"),
        default=DEFAULT_WORKERS,
        help="connection worker threads",
    )
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="configuration JSON file")
    parser.add_argument("--idle-timeout", type=float, default=DEFAULT_IDLE_TIMEOUT)
    parser.add_argument(
        "--header-limit",
        type=lambda v: positive_int(v, "header-limit"),
        default=DEFAULT_HEADER_LIMIT,
    )
    parser.add_argument(
        "--body-limit",
        type=lambda v: positive_int(v, "body-limit"),
        default=DEFAULT_BODY_LIMIT,
    )
    return parser


def configure_logging():
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%Y-%m-%d %H:%M:%S"))
    logger = logging.getLogger("gwadmin")
    logger.handlers[:] = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False


def main(argv=None):
    args = build_parser().parse_args(argv)
    configure_logging()
    app = Application(
        root=args.root,
        config_path=args.config,
        worker_count=args.workers,
        header_limit=args.header_limit,
        body_limit=args.body_limit,
    )
    server = HTTPServer(
        app,
        host=args.host,
        port=args.port,
        workers=args.workers,
        idle_timeout=args.idle_timeout,
        header_limit=args.header_limit,
        body_limit=args.body_limit,
    )
    server.install_signal_handlers()
    try:
        server.socket_pair()
    except OSError as exc:
        print(f"gwadmin: failed to bind {args.host}:{args.port}: {exc}", file=sys.stderr)
        return 1
    print(
        f"gwadmin listening on http://{server.host}:{server.port}/ "
        f"(root={args.root}, workers={args.workers})",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
