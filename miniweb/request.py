"""HTTP/1.1 request parsing, implemented from scratch on top of sockets."""

import json as _json
import re
from urllib.parse import parse_qs, unquote

from .errors import BadRequest, ConnectionClosed, PayloadTooLarge

MAX_HEADER_BYTES = 8192
MAX_BODY_BYTES = 10 * 1024 * 1024

_TOKEN_RE = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
_VERSION_RE = re.compile(r"^HTTP/(\d+)\.(\d+)$")


class Headers:
    """Case-insensitive header collection.

    Repeated header fields are merged into a single comma-separated value,
    per RFC 9110 section 5.2.
    """

    def __init__(self):
        self._store = {}  # lower name -> [original name, value]

    def add(self, name, value):
        key = name.lower()
        if key in self._store:
            self._store[key][1] += ", " + value
        else:
            self._store[key] = [name, value]

    def get(self, name, default=None):
        item = self._store.get(name.lower())
        return item[1] if item else default

    def __contains__(self, name):
        return name.lower() in self._store

    def __getitem__(self, name):
        return self._store[name.lower()][1]

    def items(self):
        return [(orig, val) for orig, val in self._store.values()]

    def __len__(self):
        return len(self._store)


class SocketReader:
    """Buffered reader over a socket with bounded header reads."""

    def __init__(self, sock):
        self.sock = sock
        self.buf = bytearray()

    def read_head(self, limit):
        """Read up to and including the CRLFCRLF terminator; return head bytes."""
        marker = b"\r\n\r\n"
        while True:
            idx = self.buf.find(marker)
            if idx != -1:
                if idx + len(marker) > limit:
                    raise BadRequest("request headers too large")
                head = bytes(self.buf[:idx])
                del self.buf[: idx + len(marker)]
                return head
            if len(self.buf) > limit:
                raise BadRequest("request headers too large")
            chunk = self.sock.recv(4096)
            if not chunk:
                if not self.buf:
                    raise ConnectionClosed()
                raise BadRequest("connection closed while reading headers")
            self.buf.extend(chunk)

    def read_exactly(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(min(65536, n - len(self.buf)))
            if not chunk:
                raise BadRequest("connection closed while reading body")
            self.buf.extend(chunk)
        data = bytes(self.buf[:n])
        del self.buf[:n]
        return data


class Request:
    """A parsed HTTP request."""

    def __init__(self, method, raw_target, path, query_string, version, headers, body):
        self.method = method
        self.raw_target = raw_target
        self.path = path
        self.query_string = query_string
        self.version = version
        self.headers = headers
        self.body = body
        self.path_params = {}

    @property
    def query(self):
        """Query string parameters as {name: [values]}."""
        return parse_qs(self.query_string, keep_blank_values=True)

    @property
    def content_type(self):
        return (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()

    @property
    def form(self):
        """Parsed application/x-www-form-urlencoded body as {name: [values]}.

        Percent-decoding and '+'-to-space are handled by parse_qs; repeated
        keys aggregate into lists.
        """
        if self.content_type != "application/x-www-form-urlencoded":
            return {}
        text = self.body.decode("utf-8", errors="replace")
        return parse_qs(text, keep_blank_values=True)

    @property
    def json(self):
        """Parsed JSON body; raises BadRequest (400) on invalid JSON."""
        try:
            return _json.loads(self.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise BadRequest("request body is not valid JSON")

    def keep_alive(self):
        conn = (self.headers.get("Connection") or "").lower()
        if self.version == "HTTP/1.1":
            return conn != "close"
        return conn == "keep-alive"


def _parse_request_line(line):
    parts = line.split(" ")
    if len(parts) != 3 or not all(parts):
        raise BadRequest("malformed request line")
    method, target, version = parts
    if not _TOKEN_RE.match(method) or method != method.upper():
        raise BadRequest("invalid method")
    m = _VERSION_RE.match(version)
    if not m or version not in ("HTTP/1.0", "HTTP/1.1"):
        raise BadRequest("unsupported HTTP version")
    if not target.startswith("/") and target != "*" and not target.startswith("http"):
        raise BadRequest("invalid request target")
    return method, target, version


def _parse_headers(lines):
    headers = Headers()
    for line in lines:
        if not line:
            continue
        if ":" not in line:
            raise BadRequest("malformed header line")
        name, _, value = line.partition(":")
        name = name.strip()
        if not name or not _TOKEN_RE.match(name):
            raise BadRequest("invalid header name")
        headers.add(name, value.strip(" \t"))
    return headers


def read_request(reader, max_header_bytes=MAX_HEADER_BYTES, max_body_bytes=MAX_BODY_BYTES):
    """Read and parse one HTTP request from the reader."""
    head = reader.read_head(max_header_bytes)
    text = head.decode("iso-8859-1")
    lines = text.split("\r\n")
    if not lines or not lines[0]:
        raise BadRequest("empty request line")

    method, target, version = _parse_request_line(lines[0])
    headers = _parse_headers(lines[1:])

    if version == "HTTP/1.1" and "Host" not in headers:
        raise BadRequest("missing Host header")

    body = b""
    content_length = headers.get("Content-Length")
    if content_length is not None:
        if not content_length.isdigit():
            raise BadRequest("invalid Content-Length")
        length = int(content_length)
        if length > max_body_bytes:
            raise PayloadTooLarge("request body too large")
        if length:
            body = reader.read_exactly(length)

    raw_path, _, query_string = target.partition("?")
    path = unquote(raw_path, errors="replace")
    if "\x00" in path:
        raise BadRequest("invalid characters in path")

    return Request(method, target, path, query_string, version, headers, body)
