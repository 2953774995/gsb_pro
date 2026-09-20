"""Self-implemented HTTP/1.1 protocol layer.

Request parsing and response serialization built purely on sockets and the
standard library. No http.server / BaseHTTPRequestHandler anywhere.
"""

import email.utils
import time
from urllib.parse import unquote, unquote_plus

SERVER_NAME = "gwadmin/1.0"
MAX_HEAD_BYTES = 8192                    # request line + headers hard limit
MAX_CONTENT_LENGTH = 16 * 1024 * 1024    # larger bodies -> 413

_STATUS_REASONS = {
    200: "OK",
    201: "Created",
    204: "No Content",
    301: "Moved Permanently",
    302: "Found",
    304: "Not Modified",
    400: "Bad Request",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    408: "Request Timeout",
    411: "Length Required",
    413: "Payload Too Large",
    414: "URI Too Long",
    500: "Internal Server Error",
    501: "Not Implemented",
    503: "Service Unavailable",
}

_TOKEN_CHARS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    "!#$%&'*+-.^_`|~"
)


class HTTPError(Exception):
    """Raised by the parser; carries the HTTP status to send back."""

    def __init__(self, status, message=""):
        super().__init__(message or reason_phrase(status))
        self.status = status
        self.message = message or reason_phrase(status)


def reason_phrase(status):
    return _STATUS_REASONS.get(status, "Unknown Status")


def http_date(ts=None):
    """RFC 7231 IMF-fixdate, e.g. 'Sun, 06 Nov 1994 08:49:37 GMT'."""
    return email.utils.formatdate(time.time() if ts is None else ts, usegmt=True)


class Headers(object):
    """Ordered, case-insensitive header collection.

    Duplicate fields are merged per RFC 7230 3.2.2: values joined with ", ".
    """

    def __init__(self, pairs=None):
        self._items = []  # list of [lower_name, original_name, value]
        if pairs:
            for name, value in pairs:
                self.add(name, value)

    def add(self, name, value):
        lower = name.lower()
        for item in self._items:
            if item[0] == lower:
                item[2] = item[2] + ", " + value
                return
        self._items.append([lower, name, value])

    def set(self, name, value):
        lower = name.lower()
        for item in self._items:
            if item[0] == lower:
                item[1], item[2] = name, value
                return
        self._items.append([lower, name, value])

    def get(self, name, default=None):
        lower = name.lower()
        for item in self._items:
            if item[0] == lower:
                return item[2]
        return default

    def __contains__(self, name):
        return self.get(name) is not None

    def items(self):
        return [(orig, value) for _lower, orig, value in self._items]

    def __iter__(self):
        return iter(self.items())

    def __len__(self):
        return len(self._items)


class Request(object):
    """A parsed HTTP request."""

    def __init__(self, method, raw_target, path, query, version, headers,
                 body, remote_addr=None):
        self.method = method
        self.raw_target = raw_target
        self.path = path
        self.query = query          # dict: name -> [values]
        self.version = version      # "HTTP/1.1"
        self.headers = headers
        self.body = body            # bytes
        self.remote_addr = remote_addr
        self.path_params = {}       # filled by the router for :param segments

    @property
    def keep_alive(self):
        conn = (self.headers.get("Connection") or "").lower()
        if "close" in conn:
            return False
        if self.version == "HTTP/1.0":
            return "keep-alive" in conn
        return True  # HTTP/1.1 defaults to keep-alive

    @property
    def content_type(self):
        raw = self.headers.get("Content-Type") or ""
        return raw.split(";", 1)[0].strip().lower()

    def form(self):
        """Parse an application/x-www-form-urlencoded body.

        Percent-decoding, '+' -> space, repeated keys aggregated into lists.
        """
        result = {}
        if not self.body:
            return result
        try:
            text = self.body.decode("utf-8", "replace")
        except Exception:
            return result
        for pair in text.split("&"):
            if not pair:
                continue
            if "=" in pair:
                key, value = pair.split("=", 1)
            else:
                key, value = pair, ""
            key = unquote_plus(key)
            value = unquote_plus(value)
            result.setdefault(key, []).append(value)
        return result

    def json(self):
        """Parse a JSON request body. Raises HTTPError(400) on bad JSON."""
        import json as _json
        try:
            text = self.body.decode("utf-8")
        except UnicodeDecodeError:
            raise HTTPError(400, "request body is not valid UTF-8")
        try:
            return _json.loads(text)
        except ValueError as exc:
            raise HTTPError(400, "invalid JSON body: %s" % exc)


def _is_valid_token(value):
    return bool(value) and all(ch in _TOKEN_CHARS for ch in value)


def _parse_query(qs):
    query = {}
    if not qs:
        return query
    for pair in qs.split("&"):
        if not pair:
            continue
        if "=" in pair:
            key, value = pair.split("=", 1)
        else:
            key, value = pair, ""
        key = unquote_plus(key)
        value = unquote_plus(value)
        query.setdefault(key, []).append(value)
    return query


def _read_head(sock_file, limit):
    """Read request line + headers up to the blank line.

    Uses readline() on the buffered reader so bytes belonging to the body
    stay in the buffer. Returns raw head bytes (without the final CRLF),
    or None on clean EOF before any data. Raises HTTPError(400) when the
    head exceeds ``limit`` bytes.
    """
    data = bytearray()
    while True:
        remaining = limit + 1 - len(data)
        if remaining <= 0:
            raise HTTPError(400, "request head exceeds %d bytes" % limit)
        line = sock_file.readline(remaining)
        if not line:
            if not data:
                return None  # clean EOF before any data
            raise HTTPError(400, "connection closed before headers completed")
        data.extend(line)
        if len(data) > limit:
            raise HTTPError(400, "request head exceeds %d bytes" % limit)
        if not line.endswith(b"\n"):
            raise HTTPError(400, "connection closed before headers completed")
        if line in (b"\r\n", b"\n"):
            return bytes(data[:-len(line)])


def read_request(sock_file, remote_addr=None, max_head=MAX_HEAD_BYTES,
                 max_body=MAX_CONTENT_LENGTH):
    """Parse one HTTP request from a buffered socket file.

    Returns a Request, or None on clean EOF (peer closed an idle keep-alive
    connection). Raises HTTPError for malformed requests.
    """
    head = _read_head(sock_file, max_head)
    if head is None:
        return None

    try:
        text = head.decode("iso-8859-1")
    except UnicodeDecodeError:
        raise HTTPError(400, "head is not decodable")

    lines = text.split("\r\n")
    request_line = lines[0]
    parts = request_line.split(" ")
    if len(parts) != 3 or any(p == "" for p in parts):
        raise HTTPError(400, "malformed request line")
    method, raw_target, version = parts

    if not _is_valid_token(method):
        raise HTTPError(400, "invalid method")
    if version not in ("HTTP/1.0", "HTTP/1.1"):
        raise HTTPError(400, "unsupported HTTP version")

    # Headers
    headers = Headers()
    for line in lines[1:]:
        if not line:
            continue
        if line[0] in " \t":
            raise HTTPError(400, "obsolete folded headers are not accepted")
        if ":" not in line:
            raise HTTPError(400, "malformed header line")
        name, value = line.split(":", 1)
        # RFC 7230: no whitespace allowed between field-name and colon.
        if not _is_valid_token(name):
            raise HTTPError(400, "invalid header name")
        headers.add(name, value.strip(" \t"))

    # Host is mandatory for HTTP/1.1
    if version == "HTTP/1.1" and "Host" not in headers:
        raise HTTPError(400, "missing Host header")

    # Target -> path + query
    if raw_target.startswith("http://") or raw_target.startswith("https://"):
        # absolute-form: strip scheme://authority
        after = raw_target.split("://", 1)[1]
        slash = after.find("/")
        raw_target = after[slash:] if slash != -1 else "/"
    if not raw_target.startswith("/"):
        raise HTTPError(400, "invalid request target")
    if "?" in raw_target:
        raw_path, raw_qs = raw_target.split("?", 1)
    else:
        raw_path, raw_qs = raw_target, ""
    try:
        path = unquote(raw_path, errors="strict")
    except Exception:
        raise HTTPError(400, "invalid percent-encoding in path")
    if "\x00" in path:
        raise HTTPError(400, "NUL byte in path")
    query = _parse_query(raw_qs)

    # Body
    transfer_encoding = (headers.get("Transfer-Encoding") or "").lower()
    if transfer_encoding and transfer_encoding != "identity":
        raise HTTPError(400, "Transfer-Encoding not supported")
    content_length_raw = headers.get("Content-Length")
    body = b""
    if content_length_raw is not None:
        if not content_length_raw.isdigit():
            raise HTTPError(400, "invalid Content-Length")
        content_length = int(content_length_raw)
        if content_length > max_body:
            raise HTTPError(413, "request body too large")
        body = _read_exact(sock_file, content_length)

    return Request(method.upper(), raw_target, path, query, version,
                   headers, body, remote_addr=remote_addr)


def _read_exact(sock_file, n):
    chunks = []
    remaining = n
    while remaining > 0:
        chunk = sock_file.read(remaining)
        if not chunk:
            raise HTTPError(400, "connection closed before body completed")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def default_error_page(status, message=""):
    phrase = reason_phrase(status)
    detail = message or phrase
    return (
        "<!DOCTYPE html>\n"
        "<html><head><meta charset=\"utf-8\">"
        "<title>{status} {phrase}</title></head>\n"
        "<body><h1>{status} {phrase}</h1><p>{detail}</p>"
        "<hr><address>{server}</address></body></html>\n"
    ).format(status=status, phrase=phrase, detail=_escape(detail),
             server=SERVER_NAME)


def _escape(text):
    return (text.replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;"))


def serialize_response(status, headers=None, body=b"", head_only=False,
                       keep_alive=True):
    """Build the raw bytes for an HTTP response.

    ``body`` may be bytes/str/None. When ``head_only`` is True (HEAD
    requests) the Content-Length header still reflects the would-be body
    size but no body bytes are emitted.
    """
    if body is None:
        body = b""
    elif isinstance(body, str):
        body = body.encode("utf-8")
    elif isinstance(body, (bytearray, memoryview)):
        body = bytes(body)
    elif not isinstance(body, bytes):
        raise TypeError("body must be bytes/str/None, got %r" % type(body))

    hdrs = Headers(headers.items() if isinstance(headers, Headers)
                   else (headers or []))
    if "Content-Type" not in hdrs:
        hdrs.set("Content-Type", "text/html; charset=utf-8")
    hdrs.set("Content-Length", str(len(body)))
    hdrs.set("Connection", "keep-alive" if keep_alive else "close")
    hdrs.set("Server", SERVER_NAME)
    hdrs.set("Date", http_date())

    lines = ["HTTP/1.1 %d %s" % (status, reason_phrase(status))]
    for name, value in hdrs.items():
        lines.append("%s: %s" % (name, value))
    head = ("\r\n".join(lines) + "\r\n\r\n").encode("iso-8859-1")
    if head_only:
        return head
    return head + body


def error_response(status, message="", head_only=False, keep_alive=True):
    body = default_error_page(status, message)
    return serialize_response(status, [("Content-Type",
                                        "text/html; charset=utf-8")],
                              body, head_only=head_only,
                              keep_alive=keep_alive)
