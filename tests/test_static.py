"""Unit tests for static file serving and traversal protection."""

import pytest

from gwadmin.http import HTTPError
from gwadmin.static import StaticFiles, guess_mime


@pytest.fixture()
def static(www_root):
    return StaticFiles(str(www_root))


def test_mime_table():
    assert guess_mime("a.html").startswith("text/html")
    assert guess_mime("a.css").startswith("text/css")
    assert guess_mime("a.js").startswith("application/javascript")
    assert guess_mime("a.png") == "image/png"
    assert guess_mime("a.svg") == "image/svg+xml"
    assert guess_mime("a.unknownext") == "application/octet-stream"


def test_serve_file(static):
    status, headers, body = static.serve("/notes.txt")
    assert status == 200
    assert body == b"hello gateway\n"
    assert headers[0][1].startswith("text/plain")


def test_serve_index_for_root(static):
    status, _, body = static.serve("/")
    assert status == 200
    assert b"<h1>gwadmin</h1>" in body


def test_serve_index_for_subdir(static):
    status, _, body = static.serve("/sub/")
    assert status == 200
    assert b"<h1>sub</h1>" in body


def test_directory_without_index_is_403(static):
    with pytest.raises(HTTPError) as err:
        static.serve("/emptydir/")
    assert err.value.status == 403


def test_missing_file_is_404(static):
    with pytest.raises(HTTPError) as err:
        static.serve("/nope.txt")
    assert err.value.status == 404


@pytest.mark.parametrize("path", [
    "/../etc/passwd",
    "/..",
    "/sub/../../etc/passwd",
    "/%2e%2e/secret",          # decoded upstream -> '/../secret'
    "/foo/../../../bar",
    "/..%2f..%2fetc/passwd",
])
def test_traversal_rejected(static, path):
    from urllib.parse import unquote
    decoded = unquote(path)
    with pytest.raises(HTTPError) as err:
        static.serve(decoded)
    assert err.value.status == 404


def test_resolve_stays_inside_root(static, www_root):
    # Normal nested paths resolve inside the root...
    resolved = static.resolve("/sub/index.html")
    assert resolved is not None
    assert resolved.startswith(str(www_root) + "/")
    # ...while any '..' segment is rejected outright (PRD hard rule).
    assert static.resolve("/sub/../notes.txt") is None
    assert static.resolve("/../../etc/passwd") is None
    assert static.resolve("/..") is None
