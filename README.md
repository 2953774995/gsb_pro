# miniweb

A minimal HTTP/1.1 web server implemented from scratch using **only the Python
standard library** (`socket`, `threading`, `concurrent.futures`, ...). It does
**not** use `http.server`, `BaseHTTPRequestHandler`, or any third-party package
(the only dev dependency is `pytest` for the test suite).

## Features

- **Hand-rolled HTTP/1.1 parsing**: request line, case-insensitive headers
  (repeated fields merged with `, ` per RFC 9110), exact `Content-Length`
  body reads, 8 KB request-line+header cap (`400` on overflow), query-string
  parameter mapping.
- **Hand-rolled response serialization**: status line plus `Content-Type`,
  `Content-Length`, `Connection`, `Server`, and `Date` headers; default error
  pages for 400/403/404/405/413/500 (and 301/302 redirects supported);
  correct `HEAD` semantics (headers only, accurate `Content-Length`).
- **Keep-alive**: HTTP/1.1 keeps connections open by default, honors
  `Connection: close`; HTTP/1.0 closes unless `Connection: keep-alive`.
  Pipelined requests on one connection work.
- **Router**: `GET`/`POST`/`PUT`/`DELETE` registration with `/users/:id` path
  parameters; unregistered paths -> `404`, wrong method -> `405` + `Allow`.
  Handlers return `(status, headers, body)` with `body` as `bytes`/`str`/`None`.
- **Middleware hooks**: `app.before_request` (may short-circuit with a
  response) and `app.after_response` (may transform the response).
- **Static files**: `--root` directory serving with a built-in MIME table,
  `index.html` for directories (`403` when missing), and strict
  directory-traversal protection (any `../` or percent-encoded escape -> `404`).
- **Concurrency**: thread pool (configurable `--workers`), 30 s idle
  connection timeout, malformed requests can never crash the process.
- **Body helpers**: `request.form` (urlencoded: `%`-decoding, `+` -> space,
  repeated keys -> lists) and `request.json` (invalid JSON -> `400`).
- **Safety net**: any uncaught handler exception becomes a `500` with no
  stack trace leaked to the client; clean shutdown on `SIGINT`.
- **Access log** to stdout: timestamp, client, method, path, status, elapsed ms.

## Usage

```bash
# start the demo app (routes /, /hello, /echo) with a static root
python3 -m miniweb --host 127.0.0.1 --port 8080 --root ./www --workers 16

# or, after `pip install .`
miniweb --port 8080
```

Try it with curl:

```bash
curl -i http://127.0.0.1:8080/hello?name=mini
curl -i -X POST -d 'name=a+b&tag=1&tag=2' http://127.0.0.1:8080/echo
curl -i -X POST -H 'Content-Type: application/json' -d '{"a":1}' http://127.0.0.1:8080/echo
curl -i http://127.0.0.1:8080/missing          # 404
curl -i -X POST http://127.0.0.1:8080/hello    # 405 + Allow
curl -i --path-as-is http://127.0.0.1:8080/../../../etc/passwd  # 404
```

## Embedding

```python
from miniweb import Application, HTTPServer

app = Application(root="./www")   # root is optional

@app.get("/users/:id")
def show_user(request):
    return 200, {"Content-Type": "text/plain"}, "user %s" % request.path_params["id"]

@app.post("/api")
def api(request):
    data = request.json           # or request.form / request.query
    return 200, {"Content-Type": "application/json"}, '{"ok": true}'

server = HTTPServer(app, host="127.0.0.1", port=8080, workers=16, timeout=30)
server.serve_forever()            # or server.start() to run in a thread
```

## Project layout

- `miniweb/request.py` — request parsing (`SocketReader`, `Request`, `Headers`)
- `miniweb/response.py` — response serialization and default error pages
- `miniweb/router.py` — method/path routing with `:param` segments
- `miniweb/static.py` — static file serving, MIME table, traversal guard
- `miniweb/app.py` — `Application`: dispatch, middleware, 500 containment
- `miniweb/server.py` — `HTTPServer`: accept loop, thread pool, keep-alive
- `miniweb/cli.py` — `python3 -m miniweb` launcher
- `tests/` — pytest suite (starts real servers on ephemeral ports)

## Tests

```bash
python3 -m pytest tests/ -v
```

The suite covers: request-parsing edge cases (bad request lines, missing
`Host`, oversized headers, `Content-Length` mismatch/invalid, malformed
characters), routing and 405/`Allow`, form and JSON bodies, static files
(MIME, `index.html`, 403/404, traversal protection), keep-alive connection
reuse and pipelining, 10+ concurrent connections, and error pages
(400/404/405/413/500 with no stack leakage).
