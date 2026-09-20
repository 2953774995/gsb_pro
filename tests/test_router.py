"""Unit tests for the Router: dispatch, 404/405, path params, middleware."""

from gwadmin.http import Headers, Request
from gwadmin.router import Router


def make_request(method="GET", path="/", query=None):
    return Request(method, path, path, query or {}, "HTTP/1.1", Headers(),
                   b"")


def ok(request):
    return 200, [("Content-Type", "text/plain")], "ok"


def test_exact_route_dispatch():
    r = Router()
    r.get("/hello")(ok)
    status, _, body = r.dispatch(make_request("GET", "/hello"))
    assert status == 200
    assert body == "ok"


def test_trailing_slashes_normalized():
    r = Router()
    r.get("/hello")(ok)
    status, _, _ = r.dispatch(make_request("GET", "/hello/"))
    assert status == 200


def test_unregistered_path_is_404():
    r = Router()
    r.get("/hello")(ok)
    status, _, _ = r.dispatch(make_request("GET", "/nope"))
    assert status == 404


def test_method_mismatch_is_405_with_allow():
    r = Router()
    r.get("/thing")(ok)

    @r.post("/thing")
    def _(request):
        return 201, [], None

    status, headers, _ = r.dispatch(make_request("DELETE", "/thing"))
    assert status == 405
    allow = dict((k.lower(), v) for k, v in headers)["allow"]
    assert "GET" in allow and "POST" in allow and "HEAD" in allow


def test_head_falls_back_to_get_route():
    r = Router()
    r.get("/thing")(ok)
    status, _, _ = r.dispatch(make_request("HEAD", "/thing"))
    assert status == 200


def test_path_params():
    r = Router()
    seen = {}

    @r.get("/devices/:device_id/ports/:port")
    def _(request):
        seen.update(request.path_params)
        return 200, [], None

    status, _, _ = r.dispatch(make_request("GET", "/devices/gw-1/ports/3"))
    assert status == 200
    assert seen == {"device_id": "gw-1", "port": "3"}


def test_path_param_does_not_match_empty_segment():
    r = Router()
    r.get("/devices/:id")(ok)
    status, _, _ = r.dispatch(make_request("GET", "/devices//"))
    assert status == 404


def test_all_method_helpers():
    r = Router()
    for method in ("get", "post", "put", "delete"):
        getattr(r, method)("/" + method)(ok)
    for method in ("GET", "POST", "PUT", "DELETE"):
        status, _, _ = r.dispatch(make_request(method, "/" + method.lower()))
        assert status == 200, method


def test_before_hook_short_circuits():
    r = Router()
    r.get("/hello")(ok)

    @r.before_request
    def _(request):
        return 401, [], "denied"

    status, _, body = r.dispatch(make_request("GET", "/hello"))
    assert status == 401
    assert body == "denied"


def test_after_hook_can_rewrite_response():
    r = Router()
    r.get("/hello")(ok)

    @r.after_request
    def _(request, response):
        status, headers, body = response
        headers.append(("X-Hook", "yes"))
        return status, headers, body

    status, headers, _ = r.dispatch(make_request("GET", "/hello"))
    assert ("X-Hook", "yes") in headers


def test_invalid_handler_return_raises_500_error():
    import pytest
    from gwadmin.http import HTTPError
    r = Router()

    @r.get("/bad")
    def _(request):
        return "not a tuple"

    with pytest.raises(HTTPError) as err:
        r.dispatch(make_request("GET", "/bad"))
    assert err.value.status == 500
