"""HTTP/1.1 wire request parser built directly over a socket file object."""

from __future__ import annotations

from typing import Optional, Tuple
from urllib.parse import unquote

from .datastructures import CaseInsensitiveDict
from .errors import BadRequest, RequestEntityTooLarge
from .request import Request

_TOKEN_CHARS = set(
    "!#$%&'*+-.^_`|~0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
)

def _valid_token(value: bytes) -> bool:
    return bool(value) and all(chr(byte) in _TOKEN_CHARS for byte in value)


def _valid_request_target(target: str) -> bool:
    # We deliberately implement an origin-form server: "/path?query" only.
    if not target or target[0] != "/" or any(ch in target for ch in " #\x00"):
        return False
    try:
        target.encode("ascii")
    except UnicodeEncodeError:
        return False
    return True


def _safe_unquote(value: str) -> str:
    decoded = unquote(value, errors="strict")
    if "\x00" in decoded:
        raise BadRequest("NUL character in request target")
    return decoded


def _parse_request_line(line: bytes) -> Tuple[str, str, str, str, str]:
    try:
        text = line.decode("latin1")
    except UnicodeDecodeError as exc:  # latin-1 does not really fail; keep defensive.
        raise BadRequest("Invalid request line encoding") from exc

    parts = text.split(" ")
    if len(parts) != 3 or not all(parts):
        raise BadRequest("Malformed request line")

    method, target, version = parts
    # Accept common token methods at parser level.  Unsupported registered
    # verbs are naturally answered with 405 by the router.
    if not _valid_token(method.encode("ascii")) or not method.isupper():
        raise BadRequest("Invalid HTTP method")
    if version not in ("HTTP/1.0", "HTTP/1.1"):
        raise BadRequest("Unsupported HTTP version")
    if not _valid_request_target(target):
        raise BadRequest("Invalid request target")

    raw_path, _, query_string = target.partition("?")
    try:
        path = _safe_unquote(raw_path)
    except UnicodeDecodeError as exc:
        raise BadRequest("Invalid percent-encoding in request path") from exc
    return method, raw_path, path, query_string, version


def _parse_header_line(line: bytes) -> Tuple[str, str]:
    try:
        text = line.decode("latin1")
    except UnicodeDecodeError as exc:
        raise BadRequest("Invalid header encoding") from exc
    if ":" not in text:
        raise BadRequest("Malformed header line")
    name, value = text.split(":", 1)
    if not name or not _valid_token(name.encode("ascii")):
        raise BadRequest("Invalid header name")
    # OWS is optional whitespace immediately around the field value.
    value = value.strip(" \t")
    if any(ord(ch) < 32 and ch != "\t" for ch in value):
        raise BadRequest("Invalid control character in header value")
    return name, value


class HTTPRequestParser:
    """Parse one request from a buffered socket stream.

    The default maximum size for request line + headers is 8192 bytes.  This
    hard limit is checked while reading, making a very long line a bounded
    memory operation rather than trusting a client to eventually send CRLF.
    """

    def __init__(
        self,
        stream,
        max_header_size: int = 8192,
        max_body_size: int = 16 * 1024 * 1024,
    ) -> None:
        self.stream = stream
        self.max_header_size = max_header_size
        self.max_body_size = max_body_size
        self.header_bytes = 0

    def _read_line(self) -> bytes:
        data = bytearray()
        while True:
            ch = self.stream.read(1)
            if not ch:
                raise BadRequest("Connection closed before complete request")
            self.header_bytes += 1
            data.extend(ch)
            if len(data) >= 2 and data[-2:] == b"\r\n":
                if self.header_bytes > self.max_header_size:
                    raise BadRequest("Request line or headers too long")
                return bytes(data)
            # A single line (including its terminating CRLF) may not exceed
            # the total header budget, so a client cannot send one huge token.
            if len(data) >= self.max_header_size:
                raise BadRequest("Request line or headers too long")

    def parse(self, remote_address: Optional[str] = None) -> Optional[Request]:
        # Tolerate one optional CRLF sent before a request (some clients do it).
        line = self._read_line()
        while line == b"\r\n":
            line = self._read_line()
        request_line = line[:-2]

        method, raw_path, path, query_string, version = _parse_request_line(
            request_line
        )
        headers = CaseInsensitiveDict()

        while True:
            line = self._read_line()
            if line == b"\r\n":
                break
            name, value = _parse_header_line(line[:-2])
            headers.add(name, value)

        if version == "HTTP/1.1" and not headers.get("host"):
            raise BadRequest("HTTP/1.1 requests must include a Host header")

        content_length = self._content_length(headers)
        if headers.get("transfer-encoding", "").lower() != "":
            # Chunked transfer coding is intentionally unsupported by this
            # teaching server.  501 would be reasonable too, but closing after
            # a 400 is safe and cannot desynchronize the connection.
            raise BadRequest("Unsupported Transfer-Encoding")

        body = b""
        if content_length is not None:
            if content_length > self.max_body_size:
                raise RequestEntityTooLarge("Request body too large")
            expect = (headers.get("expect") or "").lower()
            expect_tokens = {
                token.strip() for token in expect.split(",") if token.strip()
            }
            if (
                version == "HTTP/1.1"
                and "100-continue" in expect_tokens
                and hasattr(self.stream, "sendall")
            ):
                self.stream.sendall(b"HTTP/1.1 100 Continue" + b'\r\n\r\n')
            body = self._read_exact(content_length)

        return Request(
            method=method,
            raw_path=raw_path,
            path=path,
            query_string=query_string,
            version=version,
            headers=headers,
            body=body,
            remote_address=remote_address,
        )

    def _content_length(self, headers: CaseInsensitiveDict) -> Optional[int]:
        raw = headers.get("content-length")
        if raw is None:
            return None
        # Repeated headers have already been comma-joined.  Reject ambiguity.
        value = raw.strip()
        if not value or not value.isdigit():
            raise BadRequest("Invalid Content-Length")
        try:
            length = int(value)
        except ValueError as exc:
            raise BadRequest("Invalid Content-Length") from exc
        if length < 0:
            raise BadRequest("Invalid Content-Length")
        return length

    def _read_exact(self, length: int) -> bytes:
        if length == 0:
            return b""
        remaining = length
        chunks = []
        while remaining:
            data = self.stream.read(remaining)
            if not data:
                raise BadRequest("Connection closed before complete request body")
            remaining -= len(data)
            chunks.append(data)
        return b"".join(chunks)
