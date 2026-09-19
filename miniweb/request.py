"""HTTP/1.1 request parsing built directly on top of a buffered socket.

Only origin-form request targets (``/path?query``) are accepted, which
covers every browser/curl request a static site + JSON API needs.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlsplit

from .errors import RequestError

_TOKEN_RE = re.compile(rb"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
_METHODS = {"GET", "HEAD", "POST", "PUT", "DELETE", "OPTIONS", "PATCH",
            "CONNECT", "TRACE"}
_VERSION_RE = re.compile(r"^HTTP/1\.[01]$")
_DIGITS_RE = re.compile(r"^[0-9]+$")


@dataclass
class Request:
    method: str
    target: str
    path: str
    raw_path: str
    query_string: str
    version: str
    headers: Dict[str, str]
    header_list: List[Tuple[str, str]]
    body: bytes = b""
    params: Dict[str, str] = field(default_factory=dict)
    remote_addr: Tuple[str, int] = ("", 0)

    def get_header(self, name: str, default: Optional[str] = None) -> Optional[str]:
        return self.headers.get(name.lower(), default)

    @property
    def keep_alive(self) -> bool:
        conn = (self.get_header("connection") or "").lower()
        tokens = {t.strip() for t in conn.split(",")}
        if "close" in tokens:
            return False
        if self.version == "HTTP/1.1":
            return True
        return "keep-alive" in tokens

    @property
    def query(self) -> Dict[str, List[str]]:
        return parse_qs(self.query_string, keep_blank_values=True)

    @property
    def content_type(self) -> str:
        ctype = self.get_header("content-type") or ""
        return ctype.split(";", 1)[0].strip().lower()

    @property
    def form(self) -> Dict[str, List[str]]:
        """Parse an ``application/x-www-form-urlencoded`` body.

        Repeated keys are aggregated into a list; ``+`` becomes a space
        and percent-encoding is decoded (UTF-8 with latin-1 fallback).
        """
        if self.content_type != "application/x-www-form-urlencoded":
            return {}
        try:
            text = self.body.decode("utf-8")
        except UnicodeDecodeError:
            text = self.body.decode("latin-1")
        return parse_qs(text, keep_blank_values=True)

    def form_value(self, key: str, default: Any = None) -> Any:
        values = self.form.get(key)
        if not values:
            return default
        return values if len(values) > 1 else values[0]

    @property
    def json(self) -> Any:
        """Parse a JSON body; raise :class:`RequestError` (400) if invalid."""
        try:
            return json.loads(self.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise RequestError("Invalid JSON body", status=400) from exc


def _capped_readline(reader, limit: int) -> bytes:
    """Read one line but never buffer more than ``limit + 1`` bytes."""
    line = reader.readline(limit + 1)
    if line and not line.endswith(b"\n"):
        # Either the line genuinely exceeded the cap, or the peer sent
        # exactly `limit` bytes of payload right at EOF; in both cases
        # the framing is unusable.
        raise RequestError("Request line/header too long")
    return line


def _strip_eol(line: bytes) -> bytes:
    if line.endswith(b"\n"):
        line = line[:-1]
    if line.endswith(b"\r"):
        line = line[:-1]
    return line


def _read_exact(reader, length: int) -> bytes:
    """Read exactly ``length`` bytes; short reads mean a closed peer."""
    chunks = []
    remaining = length
    while remaining > 0:
        chunk = reader.read(remaining)
        if not chunk:
            raise RequestError("Connection closed while reading body")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _read_chunked(reader, max_body_size: int) -> bytes:
    """Decode a ``Transfer-Encoding: chunked`` body."""
    body = bytearray()
    while True:
        size_line = _strip_eol(_capped_readline(reader, 1024))
        size_part = size_line.split(b";", 1)[0].strip()
        if not size_part or not _DIGITS_RE.match(size_part.decode("ascii")):
            raise RequestError("Invalid chunk size")
        chunk_size = int(size_part, 16)
        if chunk_size == 0:
            # Trailer section (possibly empty) up to the final CRLF.
            while True:
                line = _strip_eol(_capped_readline(reader, 64 * 1024))
                if line == b"":
                    break
            break
        if len(body) + chunk_size > max_body_size:
            raise RequestError("Request body too large", status=413)
        body.extend(_read_exact(reader, chunk_size))
        if _strip_eol(_capped_readline(reader, 2)) != b"":
            raise RequestError("Malformed chunk framing")
    return bytes(body)


def read_request(reader, writer, config) -> Request:
    """Parse one HTTP/1.1 request from a buffered ``reader``.

    Raises :class:`RequestError` for every framing/validation failure.
    """
    # ---- Request line --------------------------------------------------
    request_line = _strip_eol(_capped_readline(reader, config.max_header_size))
    if request_line == b"":
        # Idle keep-alive connection half-closed by the peer: not an error.
        raise EOFError()
    try:
        line_text = request_line.decode("latin-1")
    except Exception as exc:  # pragma: no cover - latin-1 cannot fail
        raise RequestError("Unreadable request line") from exc
    parts = line_text.split(" ")
    if len(parts) != 3 or any(part == "" for part in parts):
        raise RequestError("Malformed request line")
    method, target, version = parts
    if method not in _METHODS:
        raise RequestError("Unsupported method")
    if not _VERSION_RE.match(version):
        raise RequestError("Unsupported HTTP version")
    if not target.startswith("/"):
        raise RequestError("Invalid request target")

    # ---- Headers -------------------------------------------------------
    header_list: List[Tuple[str, str]] = []
    total = len(request_line)
    while True:
        line = _capped_readline(reader, config.max_header_size)
        total += len(line)
        if total > config.max_header_size:
            raise RequestError("Headers too long")
        line = _strip_eol(line)
        if line == b"":
            break
        colon = line.find(b":")
        if colon <= 0:
            raise RequestError("Malformed header line")
        raw_name, raw_value = line[:colon], line[colon + 1:]
        if not _TOKEN_RE.match(raw_name):
            raise RequestError("Invalid header name")
        name = raw_name.decode("latin-1").lower()
        value = raw_value.decode("latin-1")
        # OWS trimming; folded whitespace is intentionally not supported.
        value = value.strip(" \t")
        header_list.append((name, value))

    # Merge duplicate headers: RFC 7230 comma-join for most fields,
    # reject ambiguous duplicates of framing/host fields.
    headers: Dict[str, str] = {}
    for name, value in header_list:
        if name in headers:
            if name in ("content-length", "host"):
                raise RequestError(f"Duplicate {name} header")
            headers[name] = headers[name] + ", " + value
        else:
            headers[name] = value

    if version == "HTTP/1.1" and "host" not in headers:
        raise RequestError("Missing Host header")

    # ---- Body ----------------------------------------------------------
    body = b""
    te = (headers.get("transfer-encoding") or "").lower()
    expect = (headers.get("expect") or "").strip().lower()
    if "chunked" in te:
        if "content-length" in headers:
            raise RequestError("Conflicting Content-Length and chunked TE")
        if expect == "100-continue" and version == "HTTP/1.1":
            writer.write(b"HTTP/1.1 100 Continue\r\n\r\n")
            writer.flush()
        body = _read_chunked(reader, config.max_body_size)
    else:
        raw_len = headers.get("content-length")
        if raw_len is not None:
            if not _DIGITS_RE.match(raw_len):
                raise RequestError("Invalid Content-Length")
            length = int(raw_len)
            if length > config.max_body_size:
                # Do not drain a body we refuse; close the connection.
                raise RequestError("Request body too large", status=413)
            if expect == "100-continue" and version == "HTTP/1.1":
                writer.write(b"HTTP/1.1 100 Continue\r\n\r\n")
                writer.flush()
            body = _read_exact(reader, length)

    # Split target into path / query (fragment is a client-side concept).
    split = urlsplit(target)
    path = split.path or "/"
    query_string = split.query

    return Request(
        method=method,
        target=target,
        path=path,
        raw_path=path,
        query_string=query_string,
        version=version,
        headers=headers,
        header_list=header_list,
        body=body,
    )
