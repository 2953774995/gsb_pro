"""Static file serving: MIME, index pages, 403/404, traversal defense."""

import os

import pytest

from miniweb import Application
from conftest import request, raw_request, start_server


@pytest.fixture
def webroot(tmp_path):
    (tmp_path / "index.html").write_text("<h1>home</h1>", encoding="utf-8")
    (tmp_path / "style.css").write_text("body { color: red; }", encoding="utf-8")
    (tmp_path / "data.json").write_text('{"k": 1}', encoding="utf-8")
    (tmp_path / "pic.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
    (tmp_path / "notes.txt").write_text("plain text", encoding="utf-8")
    (tmp_path / "blob.xyz").write_bytes(b"\x01\x02\x03")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "index.html").write_text("<h1>sub</h1>", encoding="utf-8")
    empty = tmp_path / "empty"
    empty.mkdir()
    # a secret OUTSIDE the web root
    (tmp_path.parent / "secret-outside-root.txt").write_text(
        "top secret", encoding="utf-8")
    return tmp_path


@pytest.fixture
def static_server(webroot):
    handle = start_server(app=Application(static_root=str(webroot)))
    yield handle
    handle.server.shutdown()


def test_index_page(static_server):
    status, headers, body = request(static_server.addr, "GET", "/")
    assert status == 200
    assert body == b"<h1>home</h1>"
    assert "text/html" in headers["content-type"]


def test_subdirectory_index(static_server):
    status, _, body = request(static_server.addr, "GET", "/sub/")
    assert status == 200 and body == b"<h1>sub</h1>"


def test_mime_types(static_server):
    cases = {
        "/style.css": "text/css",
        "/data.json": "application/json",
        "/pic.png": "image/png",
        "/notes.txt": "text/plain",
        "/index.html": "text/html",
    }
    for path, mime in cases.items():
        status, headers, _ = request(static_server.addr, "GET", path)
        assert status == 200, path
        assert headers["content-type"].startswith(mime), (path, headers)


def test_unknown_extension_default_mime(static_server):
    status, headers, body = request(static_server.addr, "GET", "/blob.xyz")
    assert status == 200
    assert headers["content-type"] == "application/octet-stream"
    assert body == b"\x01\x02\x03"


def test_missing_file_404(static_server):
    status, _, body = request(static_server.addr, "GET", "/missing.txt")
    assert status == 404 and b"404" in body


def test_directory_without_index_403(static_server):
    status, _, body = request(static_server.addr, "GET", "/empty/")
    assert status == 403 and b"403" in body


def test_post_to_static_405(static_server):
    status, headers, _ = request(static_server.addr, "POST", "/notes.txt",
                                 body="x")
    assert status == 405
    assert "GET" in headers["allow"]


def test_head_static(static_server):
    status, headers, body = request(static_server.addr, "HEAD", "/notes.txt")
    assert status == 200
    assert body == b""
    assert int(headers["content-length"]) == len("plain text")


@pytest.mark.parametrize("evil", [
    "/../secret-outside-root.txt",
    "/../../etc/passwd",
    "/%2e%2e/secret-outside-root.txt",
    "/%2E%2E%2Fsecret-outside-root.txt",
    "/sub/../../secret-outside-root.txt",
    "/..%2f..%2fetc%2fpasswd",
    "/....//....//etc/passwd",
    "/%2e%2e%5csecret-outside-root.txt",
])
def test_directory_traversal_blocked(static_server, evil):
    status, _, body = request(static_server.addr, "GET", evil)
    assert status == 404, evil
    assert b"top secret" not in body


def test_traversal_never_serves_secret(static_server):
    resp = raw_request(
        static_server.addr,
        b"GET /%2e%2e/secret-outside-root.txt HTTP/1.1\r\n"
        b"Host: x\r\nConnection: close\r\n\r\n")
    assert b"top secret" not in resp
    assert resp.startswith(b"HTTP/1.1 404")
