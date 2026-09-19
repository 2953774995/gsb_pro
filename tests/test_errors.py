"""Error pages, 500 safety net and response headers."""


def test_500_when_handler_raises(client):
    resp = client.request("GET", "/boom")
    assert resp.status == 500
    assert b"500" in resp.body
    # Stack traces must never reach the client.
    assert b"Traceback" not in resp.body
    assert b"kaboom" not in resp.body


def test_500_does_not_kill_server(client, server, make_client):
    assert client.request("GET", "/boom").status == 500
    fresh = make_client(server)
    assert fresh.request("GET", "/hello").status == 200


def test_error_pages_for_all_statuses(client):
    for path, expected in [
        ("/missing", 404),
        ("/boom", 500),
    ]:
        resp = client.request("GET", path)
        assert resp.status == expected
        assert b"<html" in resp.body.lower()
        assert str(expected).encode() in resp.body


def test_405_page(client):
    resp = client.request("POST", "/hello")
    assert resp.status == 405
    assert b"405" in resp.body


def test_response_has_five_required_headers(client):
    resp = client.request("GET", "/hello")
    for name in (
        "content-type",
        "content-length",
        "connection",
        "server",
        "date",
    ):
        assert name in resp.headers, name
    assert int(resp.headers["content-length"]) == len(resp.body)


def test_date_header_is_rfc_format(client):
    import email.utils

    resp = client.request("GET", "/hello")
    parsed = email.utils.parsedate_to_datetime(resp.headers["date"])
    assert parsed is not None


def test_none_body_works(server_factory, make_client):
    from miniweb import MiniWeb

    app = MiniWeb()

    @app.post("/empty")
    def empty(request):
        return 204, None, None

    srv = server_factory(app=app)
    client = make_client(srv)
    resp = client.request("POST", "/empty")
    assert resp.status == 204
    assert resp.body == b""
    assert int(resp.headers["content-length"]) == 0


def test_bytes_str_bodies(server_factory, make_client):
    from miniweb import MiniWeb

    app = MiniWeb()

    @app.get("/bytes")
    def bytes_body(request):
        return 200, None, b"\x00\x01binary"

    @app.get("/str")
    def str_body(request):
        return 200, None, "plain string"

    srv = server_factory(app=app)
    client = make_client(srv)
    assert client.request("GET", "/bytes").body == b"\x00\x01binary"
    assert client.request("GET", "/str").body == b"plain string"
