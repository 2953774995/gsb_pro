"""Response value helpers and HTTP/1.1 response serialization."""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from email.utils import format_datetime
from typing import Any, Iterable, Mapping, Optional, Tuple

from .errors import HTTPError

STATUS_REASONS = {
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
    413: "Payload Too Large",
    500: "Internal Server Error",
    501: "Not Implemented",
}

ResponseTuple = Tuple[int, Optional[Mapping[str, str]], Any]

_HEADER_NAME_CHARS = set(
    "!#$%&'*+-.^_`|~0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
)


def default_error_page(status: int, reason: str) -> bytes:
    title = f"{status} {reason}"
    safe = html.escape(title, quote=True)
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{safe}</title></head><body><h1>{safe}</h1>"
        "<p>MiniWeb</p></body></html>"
    ).encode("utf-8")


def make_error_response(error: HTTPError, head: bool = False) -> "Response":
    body = default_error_page(error.status, error.reason)
    headers = {"Content-Type": "text/html; charset=utf-8"}
    # Application headers (for example Allow on 405) remain visible while
    # Content-Type above keeps default error pages consistent.
    for key, value in error.headers.items():
        headers.setdefault(key, value)
    return Response(error.status, headers, body, head=head)


def redirect(
    location: str,
    status: int = 302,
    headers: Optional[Mapping[str, str]] = None,
) -> "Response":
    if status not in (301, 302, 303, 307, 308):
        status = 302
    merged = {"Location": location}
    if headers:
        merged.update(headers)
    body = (
        f"<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{status} {STATUS_REASONS.get(status, 'Redirect')}</title></head>"
        f"<body><p>Redirecting to <a href='{html.escape(location, quote=True)}'>"
        f"{html.escape(location)}</a>.</p></body></html>"
    ).encode("utf-8")
    return Response(status, merged, body)


def _normalize_headers(headers: Optional[Any]) -> Iterable[Tuple[str, str]]:
    if headers is None:
        return []
    if isinstance(headers, Mapping):
        return list(headers.items())
    if isinstance(headers, (list, tuple)):
        return [(str(k), str(v)) for k, v in headers]
    raise TypeError("headers must be a mapping, sequence of pairs, or None")


class Response:
    def __init__(
        self,
        status: int = 200,
        headers: Optional[Any] = None,
        body: Any = b"",
        head: bool = False,
        version: str = "HTTP/1.1",
        keep_alive: bool = True,
        server_name: str = "miniweb",
    ) -> None:
        if not isinstance(status, int) or not 100 <= status <= 599:
            raise ValueError("Invalid response status")
        self.status = status
        self.reason = STATUS_REASONS.get(status, "Response")
        self.head = head
        self.version = version
        self.keep_alive = keep_alive
        self.server_name = server_name
        self.headers = {}
        for key, value in _normalize_headers(headers):
            key = str(key)
            value = str(value)
            if not key or any(ch not in _HEADER_NAME_CHARS for ch in key):
                raise ValueError("Invalid response header name")
            if "\r" in value or "\n" in value:
                raise ValueError("CR/LF is not allowed in response header values")
            # Last duplicate wins for application-supplied response headers.
            self.headers[key.lower()] = (key, value)
        self.body_bytes = self._encode_body(body)

    def _json_response(self) -> bool:
        content_type = self.headers.get("content-type", ("", ""))[1].lower()
        return content_type.split(";", 1)[0].strip() == "application/json"

    def _encode_body(self, body: Any) -> bytes:
        if body is None:
            return b""
        if isinstance(body, str):
            return body.encode("utf-8")
        if isinstance(body, bytes):
            return body
        # The documented handler contract is bytes/str/None, but JSON is common
        # enough to serialize plain dict/list bodies when the header says JSON.
        if self._json_response():
            return json.dumps(body, ensure_ascii=False).encode("utf-8")
        return str(body).encode("utf-8")

    @classmethod
    def from_handler(
        cls,
        value: Any,
        head: bool,
        version: str,
        keep_alive: bool,
        server_name: str = "miniweb",
    ) -> "Response":
        if isinstance(value, Response):
            value.head = head
            value.version = version
            value.keep_alive = keep_alive
            value.server_name = server_name
            if "content-length" not in value.headers:
                value.headers["content-length"] = (
                    "Content-Length",
                    str(len(value.body_bytes)),
                )
            return value

        if isinstance(value, tuple):
            if len(value) != 3:
                raise TypeError("handler tuple must be (status, headers, body)")
            status, headers, body = value
        else:
            status, headers, body = 200, {}, value
        headers = dict(headers or {})
        if isinstance(body, str):
            headers.setdefault("Content-Type", "text/plain; charset=utf-8")
        elif (
            body is not None
            and not isinstance(body, bytes)
            and headers.get("Content-Type", "").lower().split(";", 1)[0].strip()
            == "application/json"
        ):
            body = json.dumps(body, ensure_ascii=False)
            headers.setdefault("Content-Type", "application/json")
        return cls(
            int(status),
            headers,
            body,
            head=head,
            version=version,
            keep_alive=keep_alive,
            server_name=server_name,
        )

    def serialize(self) -> bytes:
        body = self.body_bytes
        # RFC 9112: Content-Length is the representation length even for HEAD.
        # The body itself is omitted.
        self.headers["content-length"] = ("Content-Length", str(len(body)))
        if "content-type" not in self.headers:
            self.headers["content-type"] = (
                "Content-Type",
                "application/octet-stream" if body else "text/plain; charset=utf-8",
            )
        self.headers["connection"] = (
            "Connection",
            "keep-alive" if self.keep_alive else "close",
        )
        self.headers["server"] = ("Server", self.server_name)
        self.headers["date"] = (
            "Date",
            format_datetime(datetime.now(timezone.utc), usegmt=True),
        )

        lines = [f"{self.version} {self.status} {self.reason}"]
        for name, value in self.headers.values():
            lines.append(f"{name}: {value}")
        header_block = ("\r\n".join(lines) + "\r\n\r\n").encode("latin1")
        omit_body = self.head or self.status in (204, 304) or 100 <= self.status < 200
        return header_block if omit_body else header_block + body
