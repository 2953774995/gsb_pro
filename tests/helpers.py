import json
import socket

from miniweb.application import Application
from miniweb.response import redirect
from miniweb.router import Router


def build_app(static_root=None):
    router = Router()

    @router.get("/hello")
    def hello(request):
        return 200, {"X-Query": request.query.get("name", "default")}, "hello"

    @router.get("/users/:id")
    def users(request):
        return (
            200,
            {"Content-Type": "application/json"},
            json.dumps({"id": request.params["id"], "q": request.query}).encode(),
        )

    @router.post("/form")
    def form(request):
        return 200, {"Content-Type": "application/json"}, json.dumps(request.form)

    @router.put("/users/:id")
    def put_user(request):
        return 200, {}, ("updated " + request.params["id"])

    @router.delete("/users/:id")
    def delete_user(request):
        return 204, {}, None

    @router.post("/json")
    def json_body(request):
        data = request.json
        return 200, {"Content-Type": "application/json"}, data

    @router.get("/boom")
    def boom(request):
        raise RuntimeError("hidden")

    @router.post("/boom")
    def boom_post(request):
        raise RuntimeError("hidden")

    @router.get("/old")
    def old(request):
        return redirect("/new", status=301)

    @router.get("/short")
    def short(request):
        return redirect("/hello", status=302)

    @router.get("/middleware")
    def middleware(request):
        return 200, {}, "base"

    app = Application(router=router, static_root=str(static_root) if static_root else None)

    @app.before_request
    def add_state(request):
        request.seen_by_before = True

    @app.after_request
    def add_after_header(request, response):
        response.headers["x-after"] = ("X-After", "yes")
        if request.path == "/middleware" and request.query.get("change") == "1":
            return 201, {"X-Middleware": "short-circuited"}, "changed"

    return app



def raw_request(port, payload, timeout=3.0, read_size=8192, recvcount=20):
    with socket.create_connection(("127.0.0.1", port), timeout=timeout) as sock:
        if isinstance(payload, str):
            payload = payload.encode()
        is_head = payload.startswith(b"HEAD ")
        sock.sendall(payload)
        try:
            sock.shutdown(socket.SHUT_WR)
        except OSError:
            # A very fast error response may already have closed the peer in
            # socketpair-backed tests.  Reading queued response data remains.
            pass
        data = b""
        # For HEAD, the server must omit the message body while retaining the
        # representation Content-Length. Read one exact response by headers.
        if is_head:
            while b"\r\n\r\n" not in data:
                chunk = sock.recv(read_size)
                if not chunk:
                    break
                data += chunk
            header, _ = data.split(b"\r\n\r\n", 1)
            return header + b"\r\n\r\n"
        for _ in range(recvcount):
            chunk = sock.recv(read_size)
            if not chunk:
                break
            data += chunk
        return data


def parse_response(data):
    assert b"\r\n\r\n" in data, data
    raw_headers, body = data.split(b"\r\n\r\n", 1)
    lines = raw_headers.split(b"\r\n")
    status_line = lines[0].decode("latin1")
    version, status_text, reason = status_line.split(" ", 2)
    status = int(status_text)
    headers = {}
    for line in lines[1:]:
        name, value = line.decode("latin1").split(":", 1)
        headers[name.lower()] = value.strip()
    length = int(headers.get("content-length", "0"))
    body = body[:length] if headers.get("content-length") else body
    return status, headers, body, reason, version


def http_request(port, method, path, body=b"", headers=None, version="HTTP/1.1", keep_alive=True):
    lines = [f"{method} {path} {version}"]
    default_headers = {"Host": "localhost"}
    if body:
        if isinstance(body, str):
            body = body.encode()
        default_headers["Content-Length"] = str(len(body))
        default_headers["Content-Type"] = "text/plain"
    default_headers.update(headers or {})
    default_headers["Connection"] = "keep-alive" if keep_alive else "close"
    for key, value in default_headers.items():
        lines.append(f"{key}: {value}")
    payload = ("\r\n".join(lines) + "\r\n\r\n").encode() + body
    return parse_response(raw_request(port, payload))
