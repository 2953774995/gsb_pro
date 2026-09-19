"""HTTP/1.1 request parsing, implemented from scratch on top of sockets.

No http.server / BaseHTTPRequestHandler anywhere -- just buffered reads
on a socket file object.
"""

import json as _json
import re
from urllib.parse import parse_qs, unquote, urlsplit

from .errors import HTTPError, RequestError

#: Hard limits (defaults required by the PRD).
MAX_REQUEST_LINE = 8192          # bytes, request line
MAX_HEADERS = 8192               # bytes, cumulative header block
MAX_BODY = 16 * 1024 * 1024      # bytes, request body (413 beyond this)

_TOKEN_RE = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
_METHOD_RE = re.compile(r"^[A-Z][A-Z0-9_-]{0,31}$")
_VERSION_RE = re.compile(r"^HTTP/(\d+)\.(\d+)$")

SUPPORTED_VERSIONS = {(1, 0), (1, 1)}


class Headers(object):
    """Case-insensitive header container.

    Duplicate header fields are merged into a single comma-separated
    value, per RFC 9110 section 5.2 -- applied consistently.
    """

    def __init__(self, items=None):
        self._data = {}          # lower-name -> [original-name, value]
        if items:
            for name, value in items:
                self.add(name, value)

    def add(self, name, value):
        key = name.lower()
        if key in self._data:
            self._data[key][1] += ", " + value
        else:
            self._data[key] = [name, value]

    def get(self, name, default=None):
        item = self._data.get(name.lower())
        return item[1] if item is not None else default

    def __contains__(self, name):
        return name.lower() in self._data

    def __getitem__(self, name):
        value = self.get(name)
        if value is None:
            raise KeyError(name)
        return value

    def items(self):
        return [(orig, value) for orig, value in self._data.values()]

    def __len__(self):
        return len(self._data)

    def __repr__(self):
        return "Headers(%r)" % (self.items(),)


class Request(object):
    """A parsed HTTP request."""

    def __init__(self, method, target, path, query, version, headers, body,
                 client_addr=None):
        self.method = method
        self.target = target            # raw request target as sent
        self.path = path                # percent-decoded URL path
        self.query_string = query
        self.version = version          # e.g. "HTTP/1.1"
        self.headers = headers
        self.body = body                # bytes
        self.client_addr = client_addr
        self.path_params = {}           # filled in by the router
        #: query string parsed into {name: [values...]}
        self.args = parse_qs(query, keep_blank_values=True)

    # -- convenience helpers -------------------------------------------------
    def arg(self, name, default=None):
        """First value of a query parameter."""
        values = self.args.get(name)
        return values[0] if values else default

    @property
    def content_type(self):
        return (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()

    @property
    def form(self):
        """Parsed application/x-www-form-urlencoded body.

        Percent-decoding and '+' -> space are handled by parse_qs;
        repeated keys aggregate into lists.  Returns {} for other
        content types.
        """
        if self.content_type != "application/x-www-form-urlencoded":
            return {}
        text = self.body.decode("utf-8", "replace")
        return parse_qs(text, keep_blank_values=True)

    @property
    def json(self):
        """Parsed JSON body.  Raises HTTPError(400) on invalid JSON."""
        try:
            return _json.loads(self.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise HTTPError(400, "invalid JSON body")

    def wants_close(self):
        conn = (self.headers.get("Connection") or "").lower()
        tokens = {t.strip() for t in conn.split(",") if t.strip()}
        if "close" in tokens:
            return True
        if self.version == "HTTP/1.0":
            return "keep-alive" not in tokens
        return False  # HTTP/1.1 keeps alive by default

    def __repr__(self):
        return "<Request %s %s %s>" % (self.method, self.target, self.version)


def _readline(rfile, limit, what):
    line = rfile.readline(limit + 1)
    if len(line) > limit:
        raise RequestError(400, "%s too long" % what)
    return line


def _parse_request_line(line):
    try:
        text = line.decode("latin-1").rstrip("\r\n")
    except UnicodeDecodeError:  # latin-1 never fails, defensive only
        raise RequestError(400, "undecodable request line")
    if not text:
        raise RequestError(400, "empty request line")
    parts = text.split(" ")
    if len(parts) != 3 or any(p == "" for p in parts):
        raise RequestError(400, "malformed request line")
    method, target, version = parts
    if not _METHOD_RE.match(method):
        raise RequestError(400, "invalid method")
    m = _VERSION_RE.match(version)
    if not m or (int(m.group(1)), int(m.group(2))) not in SUPPORTED_VERSIONS:
        raise RequestError(400, "unsupported HTTP version")
    if not target:
        raise RequestError(400, "empty request target")
    return method, target, version


def _parse_target(target):
    """Split a request target into (decoded path, query string)."""
    if "://" in target:  # absolute-form: http://host/path?query
        split = urlsplit(target)
        path, query = split.path or "/", split.query
    else:
        if "?" in target:
            path, query = target.split("?", 1)
        else:
            path, query = target, ""
    if not path.startswith("/"):
        raise RequestError(400, "invalid request target")
    try:
        path = unquote(path, encoding="utf-8", errors="replace")
    except Exception:
        raise RequestError(400, "invalid percent-encoding in path")
    if "\x00" in path:
        raise RequestError(400, "NUL byte in path")
    return path, query


def _parse_headers(lines):
    headers = Headers()
    for raw in lines:
        try:
            line = raw.decode("latin-1").rstrip("\r\n")
        except UnicodeDecodeError:
            raise RequestError(400, "undecodable header line")
        if ":" not in line:
            raise RequestError(400, "malformed header line")
        name, value = line.split(":", 1)
        name = name.strip()
        if not name or not _TOKEN_RE.match(name):
            raise RequestError(400, "invalid header name")
        headers.add(name, value.strip(" \t"))
    return headers


def _content_length(headers):
    raw = headers.get("Content-Length")
    if raw is None:
        return 0
    parts = [p.strip() for p in raw.split(",")]
    if not parts or any(not p.isdigit() for p in parts):
        raise RequestError(400, "invalid Content-Length")
    if len(set(parts)) != 1:
        raise RequestError(400, "conflicting Content-Length values")
    return int(parts[0])


def read_request(rfile, conn=None, max_request_line=MAX_REQUEST_LINE,
                 max_headers=MAX_HEADERS, max_body=MAX_BODY,
                 client_addr=None):
    """Read and parse one HTTP request from ``rfile``.

    Returns a Request, or None when the peer closed the connection
    cleanly before sending anything.  Raises RequestError on any
    malformed input.
    """
    # -- request line (tolerate leading blank lines, then EOF = close) ------
    while True:
        line = _readline(rfile, max_request_line, "request line")
        if line == b"":
            return None  # clean EOF
        if line in (b"\r\n", b"\n"):
            continue
        break
    method, target, version = _parse_request_line(line)
    path, query = _parse_target(target)

    # -- header block ---------------------------------------------------------
    header_lines = []
    total = 0
    while True:
        line = _readline(rfile, max_headers, "header line")
        if line == b"":
            raise RequestError(400, "connection closed inside headers")
        if line in (b"\r\n", b"\n"):
            break
        total += len(line)
        if total > max_headers:
            raise RequestError(400, "headers too large")
        header_lines.append(line)
    headers = _parse_headers(header_lines)

    if version == "HTTP/1.1" and "Host" not in headers:
        raise RequestError(400, "missing Host header")

    if "Transfer-Encoding" in headers:
        raise RequestError(400, "Transfer-Encoding not supported")

    # -- body ------------------------------------------------------------------
    length = _content_length(headers)
    if length > max_body:
        raise RequestError(413, "request body too large")
    body = b""
    if length:
        expect = (headers.get("Expect") or "").lower()
        if expect == "100-continue" and conn is not None:
            conn.sendall(b"HTTP/1.1 100 Continue\r\n\r\n")
        body = rfile.read(length)
        if body is None or len(body) < length:
            raise RequestError(400, "incomplete request body")

    return Request(method, target, path, query, version, headers, body,
                   client_addr=client_addr)
