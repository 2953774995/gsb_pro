"""Static files: MIME types, index.html, 403/404, traversal protection."""

import pytest

from miniweb import Application, HTTPServer
from conftest import make_request


@pytest.fixture
def static_server(tmp_path):
    (tmp_path / "index.html").write_text("<h1>home</h1>")
    (tmp_path / "style.css").write_text("body{}")
    (tmp_path / "app.js").write_text("console.log(1)")
    (tmp_path / "data.json").write_text("{}")
    (tmp_path / "pic.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (tmp_path / "notes.txt").write_text("hello")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "index.html").write_text("<h1>sub</h1>")
    (tmp_path / "emptydir").mkdir()
    app = Application(root=str(tmp_path))
    srv = HTTPServer(app, host="127.0.0.1", port=0, timeout=5).start()
    yield srv
    srv.shutdown()


def get(srv, path):
    resp, sock = make_request(srv.port, "GET", path)
    sock.close()
    return resp


def test_serve_html_with_mime(static_server):
    resp = get(static_server, "/index.html")
    assert resp.status == 200
    assert resp.header("content-type").startswith("text/html")
    assert resp.body == b"<h1>home</h1>"


def test_mime_types(static_server):
    assert get(static_server, "/style.css").header("content-type").startswith("text/css")
    assert "javascript" in get(static_server, "/app.js").header("content-type")
    assert get(static_server, "/data.json").header("content-type") == "application/json"
    assert get(static_server, "/pic.png").header("content-type") == "image/png"
    assert get(static_server, "/notes.txt").header("content-type").startswith("text/plain")


def test_directory_returns_index(static_server):
    resp = get(static_server, "/")
    assert resp.status == 200
    assert resp.body == b"<h1>home</h1>"
    resp = get(static_server, "/sub/")
    assert resp.status == 200
    assert resp.body == b"<h1>sub</h1>"


def test_directory_without_index_403(static_server):
    resp = get(static_server, "/emptydir/")
    assert resp.status == 403


def test_missing_file_404(static_server):
    assert get(static_server, "/nope.txt").status == 404


def test_traversal_plain(static_server):
    assert get(static_server, "/../../../etc/passwd").status == 404


def test_traversal_encoded(static_server):
    assert get(static_server, "/%2e%2e/%2e%2e/etc/passwd").status == 404
    assert get(static_server, "/..%2f..%2fetc/passwd").status == 404
    assert get(static_server, "/%2E%2E%2Fsecret").status == 404


def test_traversal_mixed(static_server):
    assert get(static_server, "/sub/../../etc/passwd").status == 404


def test_post_to_static_405(static_server):
    resp, sock = make_request(static_server.port, "POST", "/index.html", body="x=1")
    assert resp.status == 405
    assert "GET" in resp.header("allow")
    sock.close()
