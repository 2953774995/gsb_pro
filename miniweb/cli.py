"""Command line launcher: python -m miniweb --host H --port P --root DIR."""

import argparse
import signal
import sys
import threading

from .app import Application
from .server import HTTPServer


def build_app(static_root=None):
    """Demo application used by the CLI."""
    app = Application(static_root=static_root)

    @app.get("/api/hello")
    def hello(request):
        name = request.arg("name", "world")
        return 200, [("Content-Type", "application/json")], \
            '{"message": "hello, %s"}' % name

    @app.route("/api/echo", methods=("POST", "PUT"))
    def echo(request):
        ctype = request.headers.get("Content-Type") or \
            "application/octet-stream"
        return 200, [("Content-Type", ctype)], request.body

    @app.get("/")
    def index(request):
        if app.static is not None:
            return app.static.handle(request)
        return 200, [], (
            "<!DOCTYPE html><html><body><h1>miniweb is running</h1>"
            "<p>Try /api/hello or POST to /api/echo.</p>"
            "</body></html>")

    return app


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="miniweb",
        description="A minimal HTTP/1.1 server built on raw sockets.")
    parser.add_argument("--host", default="127.0.0.1",
                        help="bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000,
                        help="bind port (default: 8000)")
    parser.add_argument("--root", default=None,
                        help="static document root directory")
    parser.add_argument("--workers", type=int, default=32,
                        help="max concurrent connections (default: 32)")
    parser.add_argument("--idle-timeout", type=float, default=30.0,
                        help="connection idle timeout in seconds (default: 30)")
    args = parser.parse_args(argv)

    app = build_app(static_root=args.root)
    server = HTTPServer(args.host, args.port, app,
                        workers=args.workers, idle_timeout=args.idle_timeout)

    def _stop(signum, frame):
        # Shutdown in a helper thread: serve_forever holds the main flow.
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    print("miniweb serving on http://%s:%d (root=%s, workers=%d)"
          % (server.host, server.port, args.root or "-", args.workers))
    try:
        server.serve_forever()
    except OSError as exc:
        print("miniweb: cannot serve on %s:%d: %s"
              % (server.host, server.port, exc), file=sys.stderr)
        return 1
    finally:
        server.shutdown()
    print("miniweb stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
