"""Percent decoding and query parsing."""
from .errors import BadRequest

_HEX = set("0123456789abcdefABCDEF")


def percent_decode(text, plus_to_space=False):
    out = bytearray()
    i = 0
    while i < len(text):
        ch = text[i]
        if ord(ch) > 127:
            raise BadRequest("Non-ASCII character in request target")
        if ch == "%":
            if i + 2 >= len(text) or text[i + 1] not in _HEX or text[i + 2] not in _HEX:
                raise BadRequest("Malformed percent encoding")
            out.append(int(text[i + 1:i + 3], 16))
            i += 3
        elif plus_to_space and ch == "+":
            out.append(32)
            i += 1
        else:
            if ch in "\r\n":
                raise BadRequest("Invalid request target")
            out.append(ord(ch))
            i += 1
    try:
        return out.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BadRequest("Invalid UTF-8 in request target") from exc


def split_target(target):
    if "#" in target:
        raise BadRequest("Fragment is not allowed in request target")
    raw_path, _, raw_query = target.partition("?")
    path = percent_decode(raw_path)
    if "\x00" in path or any(ord(c) < 32 or ord(c) == 127 for c in path):
        raise BadRequest("Control character in request path")
    return path, raw_query


def parse_query(raw_query):
    result = {}
    if not raw_query:
        return result
    for part in raw_query.split("&"):
        if not part:
            continue
        raw_key, sep, raw_value = part.partition("=")
        if not sep:
            raw_value = ""
        key = percent_decode(raw_key, True)
        value = percent_decode(raw_value, True)
        if "\x00" in key or "\x00" in value:
            raise BadRequest("NUL in query string")
        if key in result:
            old = result[key]
            result[key] = old + [value] if isinstance(old, list) else [old, value]
        else:
            result[key] = value
    return result
