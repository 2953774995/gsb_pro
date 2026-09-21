"""Self-contained HTTP/1.x request parsing and response serialization."""

import email.utils
import time

from .constants import DEFAULT_BODY_LIMIT, DEFAULT_HEADER_LIMIT, SERVER_TOKEN
from .errors import BadRequest, PayloadTooLarge
from .headers import Headers
from .request import Request
from .url import parse_query, split_target

_METHODS = {"GET", "HEAD", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"}
_STATUS_PHRASES = {
    200: "OK",
    201: "Created",
    204: "No Content",
    301: "Moved Permanently",
    302: "Found",
    400: "Bad Request",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    413: "Payload Too Large",
    500: "Internal Server Error",
    503: "Service Unavailable",
}


def _read_line(conn, size_budget):
    """Read a CRLF-delimited line, enforcing total request header budget."""
    data = bytearray()
    while len(data) < size_budget:
        try:
            ch = conn.recv(1)
        except OSError as exc:
            raise BadRequest("Connection closed while reading headers") from exc
        if not ch:
            if not data:
                raise EOFError()
            raise BadRequest("Unexpected end of connection")
        data.extend(ch)
        if ch == b"\n":
            if len(data) < 2 or data[-2] != 13:
                raise BadRequest("Header lines must use CRLF")
            if len(data) > size_budget:
                raise BadRequest("Request line or header is too long")
            return bytes(data[:-2]), size_budget - len(data)
    raise BadRequest("Request line or header is too long")


def _is_token(value):
    forbidden = set(b'()<>@,;:\\"/[]?={} \t')
    return bool(value) and all(ch > 32 and ch < 127 and ch not in forbidden for ch in value)


def _valid_header_value(value):
    return all(ch == 9 or 31 < ch != 127 for ch in value)


def _parse_request_line(line):
    try:
        text = line.decode("ascii")
    except UnicodeDecodeError as exc:
        raise BadRequest("Request line must be ASCII") from exc
    parts = text.split(" ")
    if len(parts) != 3 or any(part == "" for part in parts):
        raise BadRequest("Malformed request line")
    method, target, version = parts
    if method not in _METHODS:
        raise BadRequest("Unsupported HTTP method")
    if version not in ("HTTP/1.0", "HTTP/1.1"):
        raise BadRequest("Unsupported HTTP version")
    if not target.startswith("/") or " " in target or "\t" in target:
        raise BadRequest("Invalid request target")
    path, raw_query = split_target(target)
    return method, target, path, parse_query(raw_query), version


def _parse_headers(conn, limit):
    headers = Headers()
    remaining = limit
    while True:
        line, remaining = _read_line(conn, remaining)
        if not line:
            return headers
        if b":" not in line:
            raise BadRequest("Malformed header line")
        name_bytes, value_bytes = line.split(b":", 1)
        if not _is_token(name_bytes):
            raise BadRequest("Invalid header name")
        value_bytes = value_bytes.strip(b" \t")
        if not _valid_header_value(value_bytes):
            raise BadRequest("Invalid header value")
        name = name_bytes.decode("ascii").lower()
        if name == "host" and "host" in headers:
            raise BadRequest("Duplicate Host header")
        if name == "content-length" and "content-length" in headers:
            raise BadRequest("Duplicate Content-Length header")
        headers.add(name, value_bytes.decode("iso-8859-1"))


def _parse_content_length(headers, body_limit):
    raw = headers.get("content-length")
    if raw is None:
        return 0
    value = raw.strip()
    if not value or not value.isdigit() or (len(value) > 1 and value.startswith("0")):
        raise BadRequest("Invalid Content-Length")
    length = int(value)
    if length > body_limit:
        raise PayloadTooLarge("Request body is too large")
    return length


def _read_exact(conn, length, request=None):
    chunks = []
    remaining = length
    while remaining:
        try:
            chunk = conn.recv(min(remaining, 65536))
        except OSError as exc:
            raise BadRequest("Connection closed while reading body") from exc
        if not chunk:
            raise BadRequest(
                "Connection closed before complete request body", request=request
            )
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_request(conn, header_limit=DEFAULT_HEADER_LIMIT, body_limit=DEFAULT_BODY_LIMIT):
    line, remaining = _read_line(conn, header_limit)
    method, target, path, query, version = _parse_request_line(line)
    headers = _parse_headers(conn, remaining)
    if version == "HTTP/1.1" and "host" not in headers:
        raise BadRequest("HTTP/1.1 requests must include Host")
    if "transfer-encoding" in headers:
        raise BadRequest("Transfer-Encoding is not supported")
    preliminary = Request(method, target, path, query, version, headers, b"", peer=conn.peer)
    try:
        length = _parse_content_length(headers, body_limit)
    except PayloadTooLarge as exc:
        exc.request = preliminary
        raise
    try:
        body = _read_exact(conn, length, preliminary) if length else b""
    except BadRequest as exc:
        exc.request = preliminary
        raise
    return Request(method, target, path, query, version, headers, body, peer=conn.peer)


def default_error_page(status, message=None):
    phrase = _STATUS_PHRASES.get(status, "Error")
    safe = (message if message is not None else phrase)
    safe = (
        str(safe).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )
    html = (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        f"<title>{status} {phrase}</title></head>"
        f"<body><h1>{status} {phrase}</h1><p>{safe}</p></body></html>"
    )
    return html.encode("utf-8")


def normalize_headers(headers):
    if headers is None:
        return []
    if hasattr(headers, "items") and not isinstance(headers, list):
        return [(str(k).lower(), str(v)) for k, v in headers.items()]
    return [(str(k).lower(), str(v)) for k, v in headers]


def wants_keep_alive(request):
    tokens = {
        part.strip().lower()
        for part in request.headers.get("connection", "").split(",")
        if part.strip()
    }
    if "close" in tokens:
        return False
    if "keep-alive" in tokens:
        return True
    return request.version == "HTTP/1.1"


def _encode_body(body):
    if body is None:
        return b""
    if isinstance(body, bytes):
        return body
    if isinstance(body, str):
        return body.encode("utf-8")
    raise TypeError("Handler body must be bytes, str, or None")


def build_response(request, status, headers=None, body=None, keep_alive=True):
    if status not in _STATUS_PHRASES:
        status = 500
    raw = _encode_body(body)
    normalized = normalize_headers(headers)
    items = []
    seen = set()
    for name, value in normalized:
        # Application handlers should emit one logical value per header.
        if name in seen:
            continue
        seen.add(name)
        # Content-Length and Connection describe the actual transport, so the
        # framework must be the source of truth even if a handler supplied them.
        if name not in ("content-length", "connection"):
            items.append((name, value))
    items.append(("content-length", str(len(raw))))
    items.append(("connection", "keep-alive" if keep_alive else "close"))
    defaults = {
        "content-type": "text/html; charset=utf-8",
        "server": SERVER_TOKEN,
        "date": email.utils.formatdate(time.time(), usegmt=True),
    }
    for name, value in defaults.items():
        if name not in seen:
            items.append((name, value))
    version = "HTTP/1.1" if request and request.version == "HTTP/1.1" else "HTTP/1.0"
    lines = [f"{version} {status} {_STATUS_PHRASES[status]}"]
    for name, value in items:
        if not _is_token(name.encode("ascii")):
            raise ValueError("Invalid response header name")
        lines.append(f"{name}: {str(value).replace(chr(13), ' ').replace(chr(10), ' ')}")
    packet = ("\r\n".join(lines) + "\r\n\r\n").encode("ascii")
    return packet if request and request.method == "HEAD" else packet + raw


def build_error_response(request, status, message=None, headers=None, keep_alive=False):
    final_headers = dict(normalize_headers(headers))
    final_headers.setdefault("content-type", "text/html; charset=utf-8")
    return build_response(
        request, status, final_headers, default_error_page(status, message), keep_alive
    )
