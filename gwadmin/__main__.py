"""gwadmin command-line launcher.

Usage: python3 -m gwadmin [--host H] [--port P] [--root DIR] [--workers N]
"""

import argparse
import signal
import sys
import threading

from .app import GwAdminApp
from .server import GatewayServer


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="gwadmin",
        description="Local management agent for factory edge gateways "
                    "(pure standard-library HTTP implementation).")
    parser.add_argument("--host", default="0.0.0.0",
                        help="bind address (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8080,
                        help="listen port (default: 8080)")
    parser.add_argument("--root", default="www",
                        help="static document root (default: www)")
    parser.add_argument("--workers", type=int, default=4,
                        help="worker count reported in /api/status and used "
                             "to size the connection pool (default: 4)")
    parser.add_argument("--config", default="gwadmin-config.json",
                        help="path of the persisted config JSON file")
    parser.add_argument("--idle-timeout", type=float, default=30.0,
                        help="keep-alive idle timeout in seconds (default: 30)")
    args = parser.parse_args(argv)

    app = GwAdminApp(root=args.root, config_path=args.config,
                     workers=args.workers)
    server = GatewayServer(app, host=args.host, port=args.port,
                           workers=args.workers,
                           idle_timeout=args.idle_timeout)
    server.start()

    stop = threading.Event()

    def _handle_signal(signum, frame):
        stop.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    print("gwadmin listening on http://%s:%d (root=%s, workers=%d)" % (
        args.host, server.port, args.root, args.workers), flush=True)

    accept_thread = threading.Thread(target=server.serve_forever,
                                     daemon=True)
    accept_thread.start()
    try:
        while not stop.is_set():
            stop.wait(0.5)
    finally:
        print("shutting down...", flush=True)
        server.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
