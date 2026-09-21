"""Application composition and before/after middleware support."""

from .config_store import ConfigStore
from .constants import DEFAULT_BODY_LIMIT, DEFAULT_HEADER_LIMIT
from .errors import HTTPError
from .protocol import default_error_page
from .responses import json_response
from .router import Router
from .runtime_metadata import platform_info
from .state import RuntimeState
from .static_files import StaticFileServer


class Application:
    def __init__(
        self,
        root="static",
        config_path="data/config.json",
        worker_count=16,
        header_limit=DEFAULT_HEADER_LIMIT,
        body_limit=DEFAULT_BODY_LIMIT,
    ):
        self.router = Router()
        self.static = StaticFileServer(root)
        self.state = RuntimeState()
        self.state.set_workers(worker_count)
        self.config_store = ConfigStore(config_path)
        self.header_limit = header_limit
        self.body_limit = body_limit
        self.before_hooks = []
        self.after_hooks = []
        self._register_builtin_routes()

    def _register_builtin_routes(self):
        self.router.get("/api/status", self.status_handler)
        self.router.get("/api/config", self.config_store.get_handler)
        self.router.post("/api/config", self.config_store.update_handler)
        self.router.put("/api/config", self.config_store.update_handler)

    def before_request(self, hook):
        """Register hook(request) returning either None or a response tuple."""
        self.before_hooks.append(hook)
        return hook

    def after_response(self, hook):
        """Register hook(request, status, headers, body) -> response tuple."""
        self.after_hooks.append(hook)
        return hook

    def status_handler(self, request):
        data = self.state.snapshot()
        data.update(platform_info())
        return json_response(data)

    @staticmethod
    def _normalize_result(result):
        if not isinstance(result, tuple) or len(result) != 3:
            raise TypeError("Handler must return (status, headers, body)")
        status, headers, body = result
        return int(status), headers or {}, body

    def _run_after_hooks(self, request, status, headers, body):
        for hook in self.after_hooks:
            status, headers, body = self._normalize_result(
                hook(request, status, headers, body)
            )
        return status, headers, body

    def _static_dispatch(self, request):
        if request.method not in ("GET", "HEAD"):
            path = self.static._safe_path(request.path)
            if path.exists():
                raise HTTPError(405, "Method Not Allowed", {"Allow": "GET, HEAD"})
            raise HTTPError(404, "Not Found")
        return self.static.serve(request)

    def handle(self, request):
        try:
            for hook in self.before_hooks:
                short_circuit = hook(request)
                if short_circuit is not None:
                    status, headers, body = self._normalize_result(short_circuit)
                    return self._run_after_hooks(request, status, headers, body)
            try:
                result = self.router.dispatch(request)
            except HTTPError as exc:
                if exc.status != 404:
                    raise
                result = self._static_dispatch(request)
            status, headers, body = self._normalize_result(result)
            return self._run_after_hooks(request, status, headers, body)
        except HTTPError as exc:
            status, headers, body = (
                exc.status,
                dict(exc.headers),
                default_error_page(exc.status, exc.message),
            )
        except Exception:
            status, headers, body = (
                500,
                {},
                default_error_page(500, "Internal Server Error"),
            )
        try:
            return self._run_after_hooks(request, status, headers, body)
        except Exception:
            return 500, {}, default_error_page(500, "Internal Server Error")
