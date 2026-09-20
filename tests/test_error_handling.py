"""500 fallback, no stack leakage, and server survival under bad handlers."""

import json

from helpers import request
from conftest import SocketPairTransport


def test_handler_exception_becomes_500(app):
    @app.router.get("/api/boom")
    def _(request):
        raise RuntimeError("secret internal detail")

    env = SocketPairTransport(app)
    try:
        status, headers, body = request(env.connect, "GET", "/api/boom")
        assert status == 500
        assert b"500" in body
        # No internals leaked to the client.
        assert b"secret internal detail" not in body
        assert b"Traceback" not in body
        assert b"RuntimeError" not in body
        # Server is still alive and serving.
        status2, _, body2 = request(env.connect, "GET", "/api/status")
        assert status2 == 200
        assert json.loads(body2)["status"] == "ok"
    finally:
        env.shutdown()


def test_static_handler_oserror_survives(app):
    env = SocketPairTransport(app)
    try:
        # A path that cannot exist keeps the process healthy.
        for _ in range(3):
            status, _, _ = request(env.connect, "GET", "/definitely/missing")
            assert status == 404
    finally:
        env.shutdown()
