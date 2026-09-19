"""Command-line entry point: python -m miniweb."""

import os
import signal

from .demo import create_demo_app
from .server import Server, build_parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.port < 0 or args.port > 65535:
        parser.error("--port must be between 0 and 65535")
    if args.workers < 1:
        parser.error("--workers must be at least 1")
    static_root = os.path.abspath(os.path.expanduser(args.root)) if args.root else None
    if static_root is not None and not os.path.isdir(static_root):
        parser.error(f"static root is not a directory: {static_root}")

    app = create_demo_app(static_root=static_root)
    server = Server(
        app,
        host=args.host,
        port=args.port,
        workers=args.workers,
        timeout=args.timeout,
    )

    def request_stop(signum, frame):
        print("\nminiweb: shutting down...", flush=True)
        server.running.clear()

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, request_stop)

    print(f"miniweb listening on {server.address}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        request_stop(None, None)
    finally:
        server.shutdown(wait=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
