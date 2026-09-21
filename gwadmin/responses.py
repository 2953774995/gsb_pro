"""Response helper functions."""
import json


def json_response(data, status=200, headers=None):
    output = dict(headers or {})
    output["Content-Type"] = "application/json; charset=utf-8"
    body = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return status, output, body


def text_response(text, status=200, headers=None, content_type="text/plain; charset=utf-8"):
    output = dict(headers or {})
    output["Content-Type"] = content_type
    return status, output, text


def html_response(html, status=200, headers=None):
    return text_response(html, status, headers, "text/html; charset=utf-8")


def redirect(location, status=302, headers=None):
    output = dict(headers or {})
    output["Location"] = location
    body = (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        f"<title>{status} Redirect</title></head>"
        f'<body><a href="{location}">Moved</a></body></html>'
    )
    return status, output, body
