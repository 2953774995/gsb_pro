"""Routing, method dispatch, 404/405 and middleware tests."""

import json

from miniweb import MiniWeb


def test_get_route(client):
    resp = client.request("GET", "/hello")
    assert resp.status == 200
    assert resp.body == b"hi world"


def test_path_params(client):
    resp = client.request("GET", "/users/42")
    assert resp.status == 200
    assert resp.json() == {"id": "42"}


def test_post_route(client):
    resp = client.request(
        "POST",
        "/echo",
        headers=[("Content-Type", "application/json")],
        body=json.dumps({"a": 1}),
    )
    assert resp.status == 200
    assert resp.json() == {"a": 1}


def test_put_route(client):
    resp = client.request("PUT", "/users/7", body=b"new-data")
    assert resp.status == 200
    assert resp.json() == {"updated": "7", "body": "new-data"}


def test_delete_route(client):
    resp = client.request("DELETE", "/users/9")
    assert resp.status == 200
    assert resp.json() == {"deleted": "9"}


def test_unknown_path_is_404(client):
    resp = client.request("GET", "/no/such/thing")
    assert resp.status == 404
    assert b"404" in resp.body


def test_method_not_allowed_carries_allow(client):
    resp = client.request("POST", "/hello")
    assert resp.status == 405
    allow = resp.headers["allow"]
    assert "GET" in allow
    assert "POST" not in allow
    assert b"405" in resp.body


def test_delete_not_on_post_only_route(client):
    resp = client.request("DELETE", "/echo")
    assert resp.status == 405
    allow = {part.strip() for part in resp.headers["allow"].split(",")}
    assert "POST" in allow


def test_405_includes_head_for_get_routes(client):
    # /users/:id has GET/PUT/DELETE; POST is not allowed.
    resp = client.request("POST", "/users/3")
    assert resp.status == 405
    methods = {m.strip() for m in resp.headers["allow"].split(",")}
    assert {"GET", "HEAD", "PUT", "DELETE"} <= methods
    assert "POST" not in methods


def test_head_on_get_route_has_headers_no_body(client):
    resp = client.request("HEAD", "/hello")
    assert resp.status == 200
    assert resp.body == b""
    assert int(resp.headers["content-length"]) == len(b"hi world")


def test_explicit_close_header(client):
    resp = client.request(
        "GET", "/hello", headers=[("Connection", "close")]
    )
    assert resp.status == 200
    assert resp.headers["connection"] == "close"


def test_redirect_302(client):
    resp = client.request("GET", "/redirect")
    assert resp.status == 302
    assert resp.headers["location"] == "/hello"
    assert b"302" in resp.body


def test_middleware_before_short_circuit(server_factory, make_client):
    app = MiniWeb()

    @app.before_request
    def block_all(request):
        if request.path.startswith("/blocked"):
            return 403, {"X-Deny": "1"}, "denied"
        return None

    @app.get("/blocked/x")
    def blocked(request):
        return 200, None, "should not run"

    @app.get("/ok")
    def ok(request):
        return 200, None, "fine"

    srv = server_factory(app=app)
    client = make_client(srv)
    denied = client.request("GET", "/blocked/x")
    assert denied.status == 403
    assert denied.headers["x-deny"] == "1"
    fine = client.request("GET", "/ok")
    assert fine.status == 200
    assert fine.body == b"fine"


def test_middleware_after_sees_and_can_modify_response(server_factory, make_client):
    app = MiniWeb()

    @app.get("/ping")
    def ping(request):
        return 200, None, "pong"

    @app.after_response
    def add_footer(request, response):
        response.set_header("X-After", "yes")

    srv = server_factory(app=app)
    client = make_client(srv)
    resp = client.request("GET", "/ping")
    assert resp.status == 200
    assert resp.headers["x-after"] == "yes"
    assert resp.body == b"pong"


def test_middleware_order_and_request_mutation(server_factory, make_client):
    app = MiniWeb()

    @app.before_request
    def annotate(request):
        request.params["marker"] = "seen"

    @app.get("/m")
    def marker(request):
        return 200, None, request.params["marker"]

    srv = server_factory(app=app)
    client = make_client(srv)
    assert client.request("GET", "/m").body == b"seen"
