"""HTML escaping helpers."""

from html import escape as _html_escape


class SafeString(str):
    """A string that is already escaped / trusted and must not be escaped again."""

    __slots__ = ()


def escape_html(value):
    """Escape ``< > & " '`` for safe HTML output."""
    return _html_escape(str(value), quote=True)


def mark_safe(value):
    if isinstance(value, SafeString):
        return value
    return SafeString(str(value))
