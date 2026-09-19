"""``miniweb`` command-line launcher."""

import argparse
import json
import os
import signal
import sys
import threading

from .app import MiniWeb
from .config import Config
from .server import HttpServer


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="miniweb",
        description="A minimal HTTP/1.1 web server (stdlib only).",
    )
    parser.add_argument("--host", default="127.0.0.1", help="bind host")
    parser.add_argument("--port", type=int, default=8000, help="bind port (0 = random)")
    parser.add_argument("--root", default="", help="static files directory")
    parser.add_argument(
        "--workers",
        type=int,
        default=10,
        help="connection worker threads (thread pool size)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="idle keep-alive timeout in seconds",
    )
    return parser


def create_app(static_root: str) -> MiniWeb:
    app = MiniWeb(static_root=static_root)

    if not static_root:

        @app.get("/")
        def index(request):
            return (
                200,
                {"Content-Type": "text/html; charset=utf-8"},
                "<h1>miniweb is running</h1>",
            )

    @app.get("/hello")
    def hello(request):
        name = request.query.get("name", ["world"])[0]
        return 200, {"Content-Type": "text/plain; charset=utf-8"}, "hello, %s" % name

    @app.get("/users/:id")
    def user_detail(request):
        return (
            200,
            {"Content-Type": "application/json"},
            '{"id": "%s"}' % request.params["id"],
        )

    @app.post("/echo")
    def echo(request):
        if request.content_type == "application/json":
            return 200, {"Content-Type": "application/json"}, request.body
        data = request.form
        return (
            200,
            {"Content-Type": "application/json; charset=utf-8"},
            json.dumps({k: (v[0] if len(v) == 1 else v) for k, v in data.items()}),
        )

    return app


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    static_root = os.path.abspath(args.root) if args.root else ""
    config = Config(
        host=args.host,
        port=args.port,
        workers=args.workers,
        timeout=args.timeout,
        static_root=static_root,
    )
    app = create_app(static_root)
    server = HttpServer(app, config, logger=lambda line: print(line, flush=True))

    shutdown_event = threading.Event()

    def request_shutdown(signum, frame):
        if not shutdown_event.is_set():
            print("miniweb: received signal %d, shutting down..." % signum, flush=True)
            shutdown_event.set()
            server.shutdown(wait=False)

    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGINT, request_shutdown)
        signal.signal(signal.SIGTERM, request_shutdown)

    server.listen()
    host, port = server.address
    root_note = (" serving %s" % static_root) if static_root else ""
    print(
        "miniweb listening on http://%s:%d (workers=%d)%s"
        % (host, port, config.workers, root_note),
        flush=True,
    )
    try:
        server.serve_forever()
    finally:
        server.shutdown(wait=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
