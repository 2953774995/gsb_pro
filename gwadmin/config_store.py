"""Persistent JSON configuration for sampling and alarms."""

import json
import os
import tempfile
import threading
from pathlib import Path

from .errors import BadRequest
from .forms import parse_form, parse_json_body
from .responses import json_response

DEFAULT_CONFIG = {
    "sample_interval": 1000,
    "alarm_threshold": 85.0,
    "device_name": "edge-gateway",
    "enabled": True,
}
BOUNDS = {"sample_interval": (100, 3600000), "alarm_threshold": (0.0, 100.0)}


def _coerce_scalar(field, value):
    if field in ("sample_interval", "alarm_threshold"):
        if isinstance(value, bool):
            raise BadRequest(f"{field} must be a number")
        if isinstance(value, float) and field == "sample_interval":
            raise BadRequest("sample_interval must be an integer number of milliseconds")
        if isinstance(value, (int, float)):
            return value
        text = str(value).strip()
        if not text:
            raise BadRequest(f"{field} must be a number")
        try:
            return int(text) if field == "sample_interval" else float(text)
        except ValueError as exc:
            raise BadRequest(f"{field} must be a number") from exc
    if field == "device_name":
        value = str(value).strip()
        if not 1 <= len(value) <= 64 or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise BadRequest("device_name must contain 1-64 non-control characters")
        return value
    if field == "enabled":
        if isinstance(value, bool):
            return value
        lowered = str(value).strip().lower()
        if lowered in ("true", "1", "on", "yes"):
            return True
        if lowered in ("false", "0", "off", "no"):
            return False
        raise BadRequest("enabled must be true or false")
    raise BadRequest(f"Unknown configuration field: {field}")


def _validate(data, current):
    if not isinstance(data, dict) or not data:
        raise BadRequest("Configuration must contain one or more fields")
    merged = dict(current)
    for field, value in data.items():
        if field not in DEFAULT_CONFIG:
            raise BadRequest(f"Unknown configuration field: {field}")
        if isinstance(value, list):
            raise BadRequest(f"Duplicate or list-valued field is not allowed: {field}")
        coerced = _coerce_scalar(field, value)
        if field in BOUNDS and not BOUNDS[field][0] <= coerced <= BOUNDS[field][1]:
            low, high = BOUNDS[field]
            raise BadRequest(f"{field} must be between {low} and {high}")
        merged[field] = coerced
    return merged


class ConfigStore:
    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self.config = dict(DEFAULT_CONFIG)
        self.load()

    def load(self):
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except FileNotFoundError:
            self.persist_locked(self.config)
            return
        except (OSError, json.JSONDecodeError):
            return
        if isinstance(data, dict):
            try:
                candidate = dict(DEFAULT_CONFIG)
                candidate.update({k: v for k, v in data.items() if k in DEFAULT_CONFIG})
                self.config = _validate(candidate, DEFAULT_CONFIG)
            except BadRequest:
                self.config = dict(DEFAULT_CONFIG)

    def persist_locked(self, config):
        parent = self.path.parent
        parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=".config-", suffix=".json", dir=str(parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(config, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, self.path)
        except OSError:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    def current(self):
        with self._lock:
            return dict(self.config)

    def update(self, data):
        with self._lock:
            updated = _validate(data, self.config)
            self.persist_locked(updated)
            self.config = dict(updated)
            return dict(self.config)

    def parse_request(self, request):
        if request.method not in ("POST", "PUT"):
            raise BadRequest("Configuration update requires POST or PUT")
        content_type = request.content_type
        if content_type == "application/json":
            data = parse_json_body(request.body, request.charset)
        elif content_type in ("application/x-www-form-urlencoded", ""):
            data = parse_form(request.body, request.charset)
        else:
            raise BadRequest("Unsupported Content-Type for configuration")
        return self.update(data)

    def get_handler(self, request):
        return json_response(self.current())

    def update_handler(self, request):
        try:
            return json_response(self.parse_request(request))
        except OSError as exc:
            raise BadRequest("Failed to persist configuration") from exc
