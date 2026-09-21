import pytest

from gwadmin.app import Application
from gwadmin.errors import HTTPError
from gwadmin.request import Request
from gwadmin.headers import Headers
from gwadmin.router import Router


def make_request(method, path):
    return Request(method, path, path, {}, "HTTP/1.1", Headers())


def test_router_methods_and_path_params():
    router = Router()
    router.get("/devices/:id", lambda r: (200, {}, r.params["id"]))
    response = router.dispatch(make_request("GET", "/devices/42"))
    assert response[2] == "42"


def test_router_405_has_allow_head_inherited_from_get():
    router = Router()
    router.get("/only", lambda r: (200, {}, "ok"))
    with pytest.raises(HTTPError) as info:
        router.dispatch(make_request("POST", "/only"))
    assert info.value.status == 405
    assert "GET" in info.value.headers["Allow"]
    assert "HEAD" in info.value.headers["Allow"]


def test_router_unknown_path_404():
    router = Router()
    with pytest.raises(HTTPError) as info:
        router.dispatch(make_request("DELETE", "/missing"))
    assert info.value.status == 404


def test_application_middleware_short_circuit_and_after_hook(tmp_path):
    app = Application(root=str(tmp_path / "root"), config_path=str(tmp_path / "c.json"))

    @app.before_request
    def before(request):
        if request.path == "/blocked":
            return 403, {"X-Before": "1"}, "blocked"

    @app.after_response
    def after(request, status, headers, body):
        headers["X-After"] = "yes"
        return status, headers, body

    app.router.get("/normal", lambda r: (200, {}, "ok"))
    status, headers, _ = app.handle(make_request("GET", "/blocked"))
    assert status == 403
    assert headers["X-Before"] == "1"
    assert headers["X-After"] == "yes"
    status, headers, _ = app.handle(make_request("GET", "/normal"))
    assert status == 200 and headers["X-After"] == "yes"


def test_duplicate_response_headers_are_deduplicated(tmp_path):
    from gwadmin.protocol import build_response
    from gwadmin.app import Application

    app = Application(root=str(tmp_path / "root"), config_path=str(tmp_path / "c.json"))
    app.router.get("/dup", lambda r: (200, [("X-Dup", "a"), ("X-Dup", "b"), ("Content-Length", "999")], "ok"))
    request = make_request("GET", "/dup")
    status, headers, body = app.handle(request)
    raw = build_response(request, status, headers, body, True).lower()
    assert raw.count(b"x-dup:") == 1
    assert b"content-length: 2" in raw
    assert b"content-length: 999" not in raw


def test_302_redirect_helper():
    from gwadmin.responses import redirect

    status, headers, body = redirect("/new", 302)
    assert status == 302
    assert headers["Location"] == "/new"
    assert "302" in body


def test_all_required_route_methods():
    router = Router()
    router.post("/things", lambda r: (200, {}, "post"))
    router.put("/things/:id", lambda r: (200, {}, r.params["id"]))
    router.delete("/things/:id", lambda r: (204, {}, None))
    assert router.dispatch(make_request("POST", "/things"))[2] == "post"
    assert router.dispatch(make_request("PUT", "/things/7"))[2] == "7"
    status, _, body = router.dispatch(make_request("DELETE", "/things/7"))
    assert (status, body) == (204, None)
