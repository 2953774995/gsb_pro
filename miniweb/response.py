"""HTTP/1.1 response serialization, implemented from scratch."""

from email.utils import formatdate

SERVER_NAME = "miniweb/1.0"

STATUS_REASONS = {
    100: "Continue",
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
}

ERROR_TITLES = {
    400: "Bad Request",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    413: "Payload Too Large",
    500: "Internal Server Error",
}


def reason_phrase(status):
    return STATUS_REASONS.get(status, "Unknown")


def default_error_page(status, message=""):
    """Default HTML error page body (bytes)."""
    title = ERROR_TITLES.get(status, reason_phrase(status))
    detail = " <p>%s</p>" % _escape(message) if message else ""
    html = (
        "<!DOCTYPE html>\n"
        "<html><head><meta charset=\"utf-8\">"
        "<title>{code} {title}</title></head>\n"
        "<body><h1>{code} {title}</h1>{detail}"
        "<hr><address>{server}</address></body></html>\n"
    ).format(code=status, title=title, detail=detail, server=SERVER_NAME)
    return html.encode("utf-8")


def _escape(text):
    return (text.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def normalize_body(body):
    """handler bodies may be bytes / str / None -> bytes."""
    if body is None:
        return b""
    if isinstance(body, bytes):
        return body
    if isinstance(body, str):
        return body.encode("utf-8")
    raise TypeError("response body must be bytes, str or None, got %r"
                    % type(body))


def build_response(status, headers=None, body=None, *, method="GET",
                   version="HTTP/1.1", keep_alive=True, message=""):
    """Serialize a full HTTP response to bytes.

    Always emits Content-Type, Content-Length, Connection, Server and
    Date.  HEAD responses carry the correct Content-Length but no body.
    """
    body_bytes = normalize_body(body)
    if status >= 400 and not body_bytes:
        body_bytes = default_error_page(status, message)

    header_list = []
    if headers:
        if isinstance(headers, dict):
            header_list = list(headers.items())
        else:
            header_list = list(headers)

    present = {k.lower() for k, _ in header_list}
    if "content-type" not in present:
        if status >= 400 and not body:
            header_list.append(("Content-Type", "text/html; charset=utf-8"))
        else:
            header_list.append(("Content-Type", "text/html; charset=utf-8"))
    header_list.append(("Content-Length", str(len(body_bytes))))
    header_list.append(("Connection", "keep-alive" if keep_alive else "close"))
    if "server" not in present:
        header_list.append(("Server", SERVER_NAME))
    header_list.append(("Date", formatdate(usegmt=True)))

    lines = ["%s %d %s" % (version, status, reason_phrase(status))]
    lines += ["%s: %s" % (k, v) for k, v in header_list]
    head = ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1")

    if method.upper() == "HEAD":
        return head
    return head + body_bytes
