"""HTTP request representation and application/x-www-form-urlencoded parsing."""

import json
from typing import Any, Dict, Optional
from urllib.parse import parse_qsl

from .datastructures import CaseInsensitiveDict
from .errors import BadRequest


def aggregate_pairs(pairs) -> Dict[str, Any]:
    """Aggregate repeated keys: one value becomes str, repeats become list."""
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            old = result[key]
            result[key] = old + [value] if isinstance(old, list) else [old, value]
        else:
            result[key] = value
    return result


class Request:
    def __init__(
        self,
        method: str,
        raw_path: str,
        path: str,
        query_string: str,
        version: str,
        headers: CaseInsensitiveDict,
        body: bytes,
        remote_address: Optional[str] = None,
    ) -> None:
        self.method = method
        self.raw_path = raw_path
        self.path = path
        self.query_string = query_string
        self.version = version
        self.headers = headers
        self.body = body
        self.remote_address = remote_address
        self.params: Dict[str, str] = {}
        self._query: Optional[Dict[str, Any]] = None
        self._form: Optional[Dict[str, Any]] = None
        self._json: Any = None
        self._json_parsed = False

    @property
    def content_type(self) -> str:
        value = self.headers.get("content-type", "") or ""
        return value.split(";", 1)[0].strip().lower()

    @property
    def query(self) -> Dict[str, Any]:
        if self._query is None:
            pairs = parse_qsl(
                self.query_string,
                keep_blank_values=True,
                errors="replace",
            )
            self._query = aggregate_pairs(pairs)
        return self._query

    @property
    def form(self) -> Dict[str, Any]:
        if self._form is None:
            if self.content_type != "application/x-www-form-urlencoded":
                return {}
            text = self.body.decode("utf-8", errors="replace")
            pairs = parse_qsl(
                text,
                keep_blank_values=True,
                errors="replace",
            )
            self._form = aggregate_pairs(pairs)
        return self._form

    @property
    def json(self) -> Any:
        if not self._json_parsed:
            if self.content_type not in ("application/json", "application/vnd.api+json"):
                raise BadRequest("Expected an application/json request body")
            try:
                text = self.body.decode("utf-8")
                self._json = json.loads(text)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise BadRequest("Invalid JSON request body") from exc
            self._json_parsed = True
        return self._json
