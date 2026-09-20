"""gwadmin application: routes, management API, config persistence."""

import json
import os
import threading
import time

from .http import HTTPError
from .router import Router
from .static import StaticFiles

VERSION = "1.0.0"

DEFAULT_CONFIG = {
    "sampling_interval_ms": 1000,
    "alarm_threshold": 80.0,
    "device_name": "edge-gateway",
}

# (type, min, max) validation rules for known config keys.
_CONFIG_RULES = {
    "sampling_interval_ms": (int, 10, 3600000),
    "alarm_threshold": (float, 0.0, 10000.0),
    "device_name": (str, None, None),
}


def _json_response(payload, status=200):
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    return status, [("Content-Type", "application/json; charset=utf-8")], body


class ConfigStore(object):
    """Thread-safe JSON-file backed configuration."""

    def __init__(self, path, defaults=None):
        self.path = path
        self._lock = threading.Lock()
        self._config = dict(defaults or DEFAULT_CONFIG)
        self._load()

    def _load(self):
        if not os.path.isfile(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return  # corrupt file: keep defaults, will be overwritten on save
        if isinstance(data, dict):
            self._config.update(data)

    def get(self):
        with self._lock:
            return dict(self._config)

    def update(self, changes):
        with self._lock:
            self._config.update(changes)
            self._save_locked()

    def _save_locked(self):
        directory = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(directory, exist_ok=True)
        tmp_path = self.path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(self._config, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.replace(tmp_path, self.path)  # atomic on POSIX


def validate_config(data):
    """Validate a config dict. Returns (clean_changes, error_message)."""
    if not isinstance(data, dict):
        return None, "config payload must be an object"
    changes = {}
    for key, value in data.items():
        rule = _CONFIG_RULES.get(key)
        if rule is None:
            return None, "unknown config key: %r" % key
        typ, lo, hi = rule
        if typ is int:
            if isinstance(value, bool) or not isinstance(value, int):
                # accept numeric strings from forms
                if isinstance(value, str) and value.lstrip("-").isdigit():
                    value = int(value)
                else:
                    return None, "%s must be an integer" % key
        elif typ is float:
            if isinstance(value, bool) or \
                    not isinstance(value, (int, float)):
                if isinstance(value, str):
                    try:
                        value = float(value)
                    except ValueError:
                        return None, "%s must be a number" % key
                else:
                    return None, "%s must be a number" % key
            value = float(value)
        elif typ is str:
            if not isinstance(value, str):
                return None, "%s must be a string" % key
            if not value or len(value) > 64:
                return None, "%s must be 1..64 characters" % key
        if lo is not None and value < lo:
            return None, "%s must be >= %s" % (key, lo)
        if hi is not None and value > hi:
            return None, "%s must be <= %s" % (key, hi)
        changes[key] = value
    if not changes:
        return None, "no config keys provided"
    return changes, None


class GwAdminApp(object):
    """The management application: API endpoints + static files."""

    def __init__(self, root, config_path, workers=4):
        self.root = root
        self.workers = workers
        self.started_at = time.time()
        self._request_count = 0
        self._count_lock = threading.Lock()
        self.config = ConfigStore(config_path)
        self.static = StaticFiles(root)
        self.router = Router()
        self._register_routes()

    # -- counters ----------------------------------------------------------
    def count_request(self):
        with self._count_lock:
            self._request_count += 1

    @property
    def request_count(self):
        with self._count_lock:
            return self._request_count

    # -- routing -------------------------------------------------------------
    def _register_routes(self):
        router = self.router

        @router.get("/api/status")
        def status(request):
            uptime = time.time() - self.started_at
            return _json_response({
                "status": "ok",
                "version": VERSION,
                "uptime_seconds": round(uptime, 3),
                "workers": self.workers,
                "requests_handled": self.request_count,
            })

        @router.get("/api/config")
        def get_config(request):
            return _json_response(self.config.get())

        @router.post("/api/config")
        def post_config(request):
            ctype = request.content_type
            if ctype == "application/json":
                data = request.json()  # raises HTTPError(400) on bad JSON
            elif ctype in ("application/x-www-form-urlencoded", ""):
                form = request.form()
                data = {k: v[-1] if len(v) == 1 else v
                        for k, v in form.items()}
            else:
                raise HTTPError(400, "unsupported Content-Type: %s" % ctype)
            changes, error = validate_config(data)
            if error:
                raise HTTPError(400, error)
            self.config.update(changes)
            return _json_response({
                "status": "ok",
                "applied": changes,
                "config": self.config.get(),
            })

        @router.get("/api/devices/:device_id")
        def get_device(request):
            return _json_response({
                "id": request.path_params["device_id"],
                "online": True,
            })

    def handle(self, request):
        """Dispatch a request to API routes, falling back to static files.

        Returns (status, headers, body). HTTPError raised by handlers is
        converted by the server layer; nothing here should leak.
        """
        self.count_request()
        if request.path.startswith("/api/"):
            return self.router.dispatch(request)
        if request.method not in ("GET", "HEAD"):
            return 405, [("Allow", "GET, HEAD")], None
        return self.static.serve(request.path)
