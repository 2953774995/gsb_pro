
import pytest

from helpers import build_app
from miniweb.server import Server


@pytest.fixture
def static_root(tmp_path):
    root = tmp_path / "site"
    root.mkdir()
    (root / "index.html").write_text("<h1>index</h1>", encoding="utf-8")
    (root / "style.css").write_text("body {}", encoding="utf-8")
    sub = root / "sub"
    sub.mkdir()
    (sub / "index.html").write_text("<h1>sub index</h1>", encoding="utf-8")
    private = root / "private"
    private.mkdir()
    (private / "secret.txt").write_text("secret", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    return root


@pytest.fixture
def server(static_root):
    app = build_app(static_root)
    srv = Server(app, host="127.0.0.1", port=0, workers=16, timeout=5, access_log=False)
    srv.start(daemon=True)
    yield srv
    srv.shutdown(wait=True)


@pytest.fixture
def port(server):
    return server.bound_port

