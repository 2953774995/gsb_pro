"""Response representation, status phrases and wire serialization."""

import email.utils
from dataclasses import dataclass, field
from typing import Any, List, Optional, Tuple

from .config import SERVER_NAME

STATUS_REASONS = {
    100: "Continue",
    200: "OK",
    201: "Created",
    204: "No Content",
    301: "Moved Permanently",
    302: "Found",
    304: "Not Modified",
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    413: "Payload Too Large",
    500: "Internal Server Error",
    501: "Not Implemented",
}


def reason_for(status: int) -> str:
    return STATUS_REASONS.get(status, "Error")


def error_page(status: int, reason: str, message: Optional[str] = None) -> bytes:
    text = message or reason
    return (
        "<!DOCTYPE html>\n<html>\n<head><title>{status} {reason}</title></head>\n"
        "<body>\n<h1>{status} {reason}</h1>\n<p>{text}</p>\n"
        "<hr><p>{server}</p>\n</body>\n</html>\n"
    ).format(status=status, reason=reason, text=text, server=SERVER_NAME).encode(
        "utf-8"
    )


@dataclass
class Response:
    status: int = 200
    headers: List[Tuple[str, str]] = field(default_factory=list)
    body: bytes = b""

    def set_header(self, name: str, value: str) -> None:
        lowered = name.lower()
        self.headers = [
            (n, v) for n, v in self.headers if n.lower() != lowered
        ]
        self.headers.append((name, value))

    def get_header(self, name: str) -> Optional[str]:
        for n, v in self.headers:
            if n.lower() == name.lower():
                return v
        return None


def _coerce_body(body: Any) -> Tuple[bytes, Optional[str]]:
    if body is None:
        return b"", None
    if isinstance(body, bytes):
        return body, None
    if isinstance(body, str):
        return body.encode("utf-8"), "text/html; charset=utf-8"
    raise TypeError(
        "handler body must be bytes, str or None, got %r" % type(body).__name__
    )


def normalize(result: Any) -> Response:
    """Turn a handler result into a :class:`Response`.

    Accepted shapes: ``Response``, ``(status, headers, body)``,
    ``(status, body)`` or a bare ``body``.
    """
    if isinstance(result, Response):
        body, _ = _coerce_body(result.body)
        result.body = body
        return result
    if isinstance(result, tuple):
        if len(result) == 3:
            status, headers, body = result
        elif len(result) == 2:
            status, body = result
            headers = None
        elif len(result) == 1:
            status, headers, body = 200, None, result[0]
        else:
            raise ValueError("response tuple must have 1-3 elements")
    else:
        status, headers, body = 200, None, result
    body_bytes, default_ctype = _coerce_body(body)
    resp = Response(status=int(status), body=body_bytes)
    if headers:
        if isinstance(headers, dict):
            headers = list(headers.items())
        for name, value in headers:
            resp.headers.append((str(name), str(value)))
    if default_ctype and resp.get_header("Content-Type") is None:
        resp.set_header("Content-Type", default_ctype)
    return resp


def error_response(status: int, message: Optional[str] = None,
                   extra_headers: Optional[dict] = None) -> Response:
    reason = reason_for(status)
    body = error_page(status, reason, message)
    resp = Response(
        status=status,
        headers=[
            ("Content-Type", "text/html; charset=utf-8"),
            ("Content-Length", str(len(body))),
        ],
        body=body,
    )
    if extra_headers:
        for name, value in extra_headers.items():
            resp.set_header(name, value)
    return resp


def serialize(
    resp: Response,
    version: str,
    keep_alive: bool,
    include_body: bool = True,
) -> bytes:
    """Render the full response (or HEAD headers) onto the wire."""
    reason = reason_for(resp.status)
    lines = ["%s %d %s" % (version, resp.status, reason)]

    have = {name.lower() for name, _ in resp.headers}
    headers = list(resp.headers)
    if "content-length" not in have:
        headers.append(("Content-Length", str(len(resp.body))))
    if "content-type" not in have and resp.status not in (204, 304):
        headers.append(("Content-Type", "text/plain; charset=utf-8"))
    if "server" not in have:
        headers.append(("Server", SERVER_NAME))
    if "date" not in have:
        headers.append(("Date", email.utils.formatdate(usegmt=True)))
    if "connection" not in have:
        if version == "HTTP/1.1":
            conn = "keep-alive" if keep_alive else "close"
        else:
            conn = "keep-alive" if keep_alive else "close"
        headers.append(("Connection", conn))

    for name, value in headers:
        lines.append("%s: %s" % (name, value))

    head = ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1")
    if include_body:
        return head + resp.body
    return head
