"""Form / JSON body parsing and HEAD semantics."""

import json

from miniweb import Application, HTTPServer
from conftest import make_request


def make_body_server():
    app = Application()

    @app.post("/form")
    def form(request):
        data = request.form
        return 200, {"Content-Type": "application/json"}, json.dumps(data)

    @app.post("/json")
    def json_route(request):
        data = request.json
        return 200, {"Content-Type": "application/json"}, json.dumps({"got": data})

    @app.get("/page")
    def page(request):
        return 200, {}, "x" * 100

    srv = HTTPServer(app, host="127.0.0.1", port=0, timeout=5).start()
    return srv


def test_form_urlencoded_parsing():
    srv = make_body_server()
    try:
        body = "name=hello+world&tag=a&tag=b&empty=&pct=%3Chtml%3E"
        resp, sock = make_request(
            srv.port, "POST", "/form",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            body=body,
        )
        assert resp.status == 200
        data = json.loads(resp.body)
        assert data["name"] == ["hello world"]
        assert data["tag"] == ["a", "b"]
        assert data["empty"] == [""]
        assert data["pct"] == ["<html>"]
        sock.close()
    finally:
        srv.shutdown()


def test_json_body_parsing():
    srv = make_body_server()
    try:
        resp, sock = make_request(
            srv.port, "POST", "/json",
            headers={"Content-Type": "application/json"},
            body='{"a": 1, "b": [2, 3]}',
        )
        assert resp.status == 200
        assert json.loads(resp.body)["got"] == {"a": 1, "b": [2, 3]}
        sock.close()
    finally:
        srv.shutdown()


def test_invalid_json_returns_400():
    srv = make_body_server()
    try:
        resp, sock = make_request(
            srv.port, "POST", "/json",
            headers={"Content-Type": "application/json"},
            body="{not json",
        )
        assert resp.status == 400
        sock.close()
    finally:
        srv.shutdown()


def test_head_returns_headers_only():
    srv = make_body_server()
    try:
        resp, sock = make_request(srv.port, "HEAD", "/page")
        assert resp.status == 200
        assert resp.header("content-length") == "100"
        assert resp.body == b""
        sock.close()
    finally:
        srv.shutdown()
