"""JSON and urlencoded form body parsers."""
import json
from .errors import BadRequest
from .url import percent_decode


def parse_form(body, charset="utf-8"):
    try:
        text = body.decode(charset) if isinstance(body, bytes) else body
    except (UnicodeDecodeError, LookupError) as exc:
        raise BadRequest("Invalid form encoding") from exc
    result = {}
    if not text:
        return result
    for part in text.split("&"):
        if not part:
            continue
        raw_key, has_equal, raw_value = part.partition("=")
        if not has_equal:
            raw_value = ""
        key = percent_decode(raw_key, True)
        value = percent_decode(raw_value, True)
        if "\x00" in key or "\x00" in value:
            raise BadRequest("NUL in form body")
        if key in result:
            old = result[key]
            result[key] = old + [value] if isinstance(old, list) else [old, value]
        else:
            result[key] = value
    return result


def parse_json_body(body, charset="utf-8"):
    if not body:
        raise BadRequest("Request body must not be empty")
    try:
        return json.loads(body.decode(charset))
    except (UnicodeDecodeError, LookupError) as exc:
        raise BadRequest("Invalid JSON character encoding") from exc
    except json.JSONDecodeError as exc:
        raise BadRequest("Invalid JSON body") from exc
