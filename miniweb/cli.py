"""Command-line launcher: python3 -m miniweb [--host H] [--port P] [--root DIR] [--workers N]."""

import argparse
import json
import signal
import sys

from .app import Application
from .server import HTTPServer


def build_app(root=None):
    """Demo application: a few routes plus optional static file serving."""
    app = Application(root=root)

    @app.get("/")
    def index(request):
        return 200, {"Content-Type": "text/plain; charset=utf-8"}, \
            "miniweb is running. Try /hello, POST /echo, or files under --root.\n"

    @app.get("/hello")
    def hello(request):
        name = request.query.get("name", ["world"])[0]
        return 200, {"Content-Type": "text/plain; charset=utf-8"}, \
            "Hello, %s!\n" % name

    @app.post("/echo")
    def echo(request):
        if request.content_type == "application/json":
            data = request.json
            return 200, {"Content-Type": "application/json"}, json.dumps({"json": data})
        form = request.form
        return 200, {"Content-Type": "application/json"}, json.dumps({"form": form})

    return app


def main(argv=None):
    parser = argparse.ArgumentParser(prog="miniweb",
                                     description="A minimal HTTP/1.1 web server.")
    parser.add_argument("--host", default="127.0.0.1", help="bind host (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8080, help="bind port (default 8080)")
    parser.add_argument("--root", default=None, help="static files root directory")
    parser.add_argument("--workers", type=int, default=16, help="worker threads (default 16)")
    parser.add_argument("--timeout", type=float, default=30.0,
                        help="idle connection timeout in seconds (default 30)")
    args = parser.parse_args(argv)

    app = build_app(root=args.root)
    server = HTTPServer(app, host=args.host, port=args.port,
                        workers=args.workers, timeout=args.timeout)

    def handle_sigint(signum, frame):
        print("\nshutting down...", flush=True)
        server.shutdown()

    signal.signal(signal.SIGINT, handle_sigint)

    host, port = server.server_address
    print("miniweb serving on http://%s:%d (workers=%d%s)"
          % (host, port, args.workers,
             ", root=%s" % args.root if args.root else ""), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
