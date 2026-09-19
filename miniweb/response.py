"""HTTP/1.1 response serialization."""

from email.utils import formatdate
from html import escape

SERVER_NAME = "miniweb/1.0"

REASONS = {
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
}


def reason_phrase(status):
    return REASONS.get(status, "Unknown")


def http_date():
    return formatdate(usegmt=True)


def default_error_body(status, message=None):
    reason = reason_phrase(status)
    detail = escape(message) if message else reason
    return (
        "<!DOCTYPE html>\n"
        "<html><head><title>{0} {1}</title></head>\n"
        "<body><h1>{0} {1}</h1>\n"
        "<p>{2}</p>\n"
        "<hr><address>{3}</address></body></html>\n"
    ).format(status, reason, detail, SERVER_NAME)


class Response:
    """An HTTP response. Body may be bytes, str, or None."""

    def __init__(self, status=200, headers=None, body=None):
        self.status = status
        self.headers = dict(headers or {})
        self.body = body

    @classmethod
    def error(cls, status, message=None, headers=None):
        merged = {"Content-Type": "text/html; charset=utf-8"}
        merged.update(headers or {})
        return cls(status, merged, default_error_body(status, message))

    def body_bytes(self):
        if self.body is None:
            return b""
        if isinstance(self.body, bytes):
            return self.body
        if isinstance(self.body, str):
            return self.body.encode("utf-8")
        raise TypeError("response body must be bytes, str, or None")

    def to_bytes(self, head_only=False, keep_alive=True):
        body = self.body_bytes()

        final = {}
        for name, value in self.headers.items():
            final[name.lower()] = (name, str(value))
        defaults = {
            "content-type": ("Content-Type", "text/html; charset=utf-8"),
            "content-length": ("Content-Length", str(len(body))),
            "connection": ("Connection", "keep-alive" if keep_alive else "close"),
            "server": ("Server", SERVER_NAME),
            "date": ("Date", http_date()),
        }
        for key, pair in defaults.items():
            final.setdefault(key, pair)

        lines = ["HTTP/1.1 {0} {1}".format(self.status, reason_phrase(self.status))]
        lines.extend("{0}: {1}".format(name, value) for name, value in final.values())
        head = ("\r\n".join(lines) + "\r\n\r\n").encode("iso-8859-1")
        if head_only:
            return head
        return head + body
