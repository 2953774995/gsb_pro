# miniweb

A minimal HTTP/1.1 web server implemented **from scratch** using only the
Python standard library. No `http.server`, no `BaseHTTPRequestHandler`, no
third-party runtime dependencies — just `socket`, `threading` and friends.

## Features

- **Hand-written HTTP/1.1 parser**
  - request line (`METHOD PATH HTTP/1.x`), case-insensitive headers
  - duplicate headers merged per RFC 7230 (comma-joined); duplicate
    `Host`/`Content-Length` rejected with 400
  - body read precisely by `Content-Length` (invalid length → 400,
    oversize → 413); `Transfer-Encoding: chunked` also supported
  - request line / header block capped at 8 KB by default → 400
  - query string parsed into a multi-value mapping
  - `Expect: 100-continue` supported; HTTP/1.1 without `Host` → 400
- **Hand-written response serializer**
  - always emits `Content-Type`, `Content-Length`, `Connection`, `Server`,
    `Date`
  - status codes 200/201/204/301/302/304/400/401/403/404/405/413/500 with
    built-in HTML error pages
  - `HEAD` returns headers only with correct `Content-Length`
  - Keep-Alive semantics for HTTP/1.1 (default on) and HTTP/1.0
    (`Connection: keep-alive` opt-in)
- **Router**
  - `GET` / `POST` / `PUT` / `DELETE` (+ `PATCH`, `OPTIONS`)
  - path parameters: `/users/:id`
  - unregistered path → 404; wrong method → 405 with `Allow` header
  - registered `GET` also answers `HEAD`
  - handlers: `handler(request) -> (status, headers, body)` with
    `body` as `bytes | str | None` (also accepts `Response`, 2-tuples)
  - `before_request` / `after_response` middleware hooks
- **Static files (`--root`)**
  - built-in MIME table (html/css/js/json/png/jpeg/gif/svg/…)
  - directory → `index.html`, missing index → 403, unknown path → 404
  - `/dir` → 301 → `/dir/`
  - strict traversal protection: decoded `..` segments, encoded
    variants (`%2e%2e`, `%2f`, `%5c` …) and symlink escapes all → 404;
    final resolved path must live inside the web root
- **Concurrency & resilience**
  - thread pool (one worker per accepted connection), N concurrent
    connections served in parallel
  - idle keep-alive timeout (default 30 s) closes stale connections
  - malformed traffic always produces a 400/413 or a closed connection —
    the server process never crashes; handler exceptions become 500 with
    no traceback leaked
  - clean shutdown on `SIGINT`/`SIGTERM`: stops accepting and closes
    existing connections
- **Body helpers**
  - `application/x-www-form-urlencoded`: percent-decoding, `+` → space,
    repeated keys aggregated to a list
  - JSON bodies via stdlib `json`; invalid JSON → 400
- **CLI launcher** with `--host --port --root --workers --timeout` and
  access logs to stdout (time, method, path, status, elapsed ms)

## Requirements

- Python 3.8+ (developed/tested on Python 3.9)
- pytest is the only dev dependency (tests use raw TCP sockets, not
  `http.client`/`requests`)

## Quick start

```bash
# static site
python3 -m miniweb --root ./tests/static --port 8000

# install the console script (optional, editable install)
pip install -e .
miniweb --host 127.0.0.1 --port 8000 --root ./tests/static --workers 8
```

Try it with curl:

```bash
curl -i http://127.0.0.1:8000/                 # index.html
curl -i http://127.0.0.1:8000/style.css        # MIME by extension
curl -i http://127.0.0.1:8000/hello?name=ann   # JSON API demo route
curl -i -X POST -d 'name=al&tag=x&tag=y' \
     http://127.0.0.1:8000/echo                # form -> JSON echo
curl -i http://127.0.0.1:8000/nope             # 404 page
curl -i -X DELETE http://127.0.0.1:8000/hello  # 405 + Allow
curl -i -X GET -H 'X-Big: '"$(python3 -c 'print("a"*9000)')" \
     http://127.0.0.1:8000/                    # 400 header too long
curl -i --path-as-is 'http://127.0.0.1:8000/../etc/passwd'  # 404
```

Access logs look like:

```
miniweb listening on http://127.0.0.1:8000 (workers=8) serving /srv/www
2026-09-19 10:00:00 GET /hello 200 0.42ms
2026-09-19 10:00:01 POST /echo 200 0.77ms
```

## Usage as a library

```python
from miniweb import MiniWeb, Config, HttpServer

app = MiniWeb(static_root="./public")

@app.get("/users/:id")
def show_user(request):
    return 200, {"Content-Type": "application/json"}, \
        b'{"id": "%s"}' % request.params["id"].encode()

@app.post("/users")
def create_user(request):
    data = request.json                      # 400 if JSON is invalid
    return 201, None, b"created"

@app.before_request
def require_auth(request):
    if request.path.startswith("/admin") and not request.get_header("X-Token"):
        return 401, None, "auth required"     # short-circuits the handler

@app.after_response
def add_header(request, response):
    response.set_header("X-Test", "1")

server = HttpServer(app, Config(host="127.0.0.1", port=8000, workers=8))
server.serve_forever()
```

Handler return shapes:

| Return value | Meaning |
| --- | --- |
| `body` | `200 OK` with that body |
| `(status, body)` | custom status |
| `(status, headers, body)` | full control; `headers` may be dict/list |
| `Response(status, headers, body)` | direct construction |

`Request` essentials: `method`, `path`, `raw_path`, `query_string`,
`version`, `headers` (lower-cased dict), `header_list`, `body` (bytes),
`params` (path parameters), `query` / `form` (`dict[str, list[str]]`),
`json`, `content_type`, `get_header(name)`, `keep_alive`, `remote_addr`.

## Project layout

```
miniweb/
  __init__.py     public API exports
  config.py       Config dataclass and limits/defaults
  errors.py       RequestError / HTTPError
  request.py      HTTP/1.1 request parser (request line, headers, body)
  response.py     Response, status table, serializer, error pages
  router.py       pattern router with :params and 404/405 handling
  static.py       static files, MIME table, traversal protection
  app.py          middleware + dispatch + per-connection loop
  server.py       thread-pool TCP server, idle timeout, shutdown
  cli.py          command line launcher and demo routes
  __main__.py     `python -m miniweb`
tests/
  conftest.py              real-server fixtures + tiny raw HTTP client
  test_parsing.py          parser boundaries / malformed traffic
  test_routing.py          dispatch, 404/405/Allow, middleware
  test_bodies.py           form and JSON parsing
  test_static.py           MIME, index, 403/404, traversal, symlink
  test_connection.py       keep-alive, concurrency, timeout, shutdown
  test_errors.py           error pages, 500 safety net, headers
  test_units.py            pure unit tests for router/static/serializer
  test_pair_transport.py   same handler path over socketpair
  test_cli.py              CLI args + subprocess end-to-end test
  static/                  sample document root used by tests
```

## Tests

```bash
python3 -m pytest tests/ -v
```

Every integration test starts the real server on an ephemeral port
(`--port 0`) and talks to it over genuine TCP sockets with a tiny raw
HTTP/1.1 client — covering:

- parser boundaries (bad request line, missing `Host`, oversize headers,
  `Content-Length` mismatch, non-ASCII bytes, duplicate framing headers)
- routing and method dispatch, including 405/`Allow` and `HEAD`
- form (percent-decode, `+`, repeated keys) and JSON (valid/invalid)
- static files: MIME mapping, default page, 404/403, nine traversal
  payloads, encoded paths, symlink escape
- keep-alive reuse (20 sequential requests on one socket)
- 12+ concurrent connections with unique payloads, no cross-talk,
  mixed with garbage connections
- idle timeout, explicit `Connection: close`, shutdown closing idle
  connections, 500 safety net and every error page

### Note for restricted sandboxes

The integration fixture binds a real TCP port. When the OS forbids
socket binding (some CI/sandbox profiles), it transparently falls back
to an AF_UNIX `socketpair` transport that executes the *same*
`MiniWeb.handle_connection` byte-level code path; the standalone
subprocess CLI test is skipped in that case. On a normal machine all
tests use real TCP.

## Security notes

- header/request-line size cap (8 KB) and body size cap (default 2 MB)
- `..`, percent-encoded traversal and backslash tricks rejected before
  any filesystem access, plus a `realpath` containment check afterwards
- request exceptions map to 4xx; handler exceptions map to a generic 500
  page — tracebacks are logged to `app.last_error`, never sent to clients
- framing errors close the connection; clients cannot desync pipelining
