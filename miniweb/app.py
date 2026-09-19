"""The MiniWeb application: middleware, routing, static files, connection loop."""

import time
import traceback
from typing import Any, Callable, List, Optional
from urllib.parse import unquote

from .config import Config
from .errors import HTTPError, RequestError
from .request import Request, read_request
from .response import Response, error_response, normalize, serialize
from .router import Router
from .static import serve_static

BeforeHook = Callable[[Request], Optional[Any]]
AfterHook = Callable[[Request, Response], Optional[Any]]


class MiniWeb:
    def __init__(self, static_root: str = "", name: str = "miniweb") -> None:
        self.router = Router()
        self.static_root = static_root
        self.name = name
        self._before: List[BeforeHook] = []
        self._after: List[AfterHook] = []
        self.logger: Optional[Callable[[str], None]] = None
        self.last_error: Optional[str] = None

    # ---- registration sugar -------------------------------------------
    def get(self, path: str) -> Callable:
        return self.router.get(path)

    def post(self, path: str) -> Callable:
        return self.router.post(path)

    def put(self, path: str) -> Callable:
        return self.router.put(path)

    def delete(self, path: str) -> Callable:
        return self.router.delete(path)

    def add_route(self, method: str, path: str, handler: Callable) -> None:
        self.router.add(method, path, handler)

    def before_request(self, hook: BeforeHook) -> BeforeHook:
        self._before.append(hook)
        return hook

    def after_response(self, hook: AfterHook) -> AfterHook:
        self._after.append(hook)
        return hook

    # ---- dispatch ------------------------------------------------------
    def _static_fallback(self, request: Request) -> Response:
        if not self.static_root:
            raise HTTPError(404)
        return serve_static(self.static_root, request.path, head=False)

    def dispatch(self, request: Request) -> Response:
        for hook in self._before:
            result = hook(request)
            if result is not None:
                return normalize(result)

        try:
            handler, params = self.router.match(request.method, request.path)
        except HTTPError as exc:
            if exc.status == 404:
                result = self._static_fallback(request)
                response = normalize(result)
            else:
                response = error_response(
                    exc.status, exc.message, exc.headers
                )
                if exc.body is not None:
                    response.body = exc.body
        else:
            merged = {
                key: unquote(value) for key, value in params.items()
            }
            merged.update(request.params)
            request.params = merged
            response = normalize(handler(request))

        for hook in self._after:
            result = hook(request, response)
            if result is not None:
                response = normalize(result)
        return response

    def _safe_dispatch(self, request: Request) -> Response:
        try:
            return self.dispatch(request)
        except HTTPError as exc:
            response = error_response(exc.status, exc.message, exc.headers)
            if exc.body is not None:
                response.body = exc.body
        except RequestError as exc:
            response = error_response(exc.status, exc.message)
        except Exception as exc:  # noqa: BLE001 - last-resort safety net
            # Never leak a traceback to the client.
            self.last_error = "".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)
            )
            response = error_response(500)
        return response

    # ---- per-connection loop ------------------------------------------
    def handle_connection(self, reader, writer, addr, config: Config,
                          sock=None) -> None:
        self._log_client_open(addr)
        try:
            while True:
                try:
                    request = read_request(reader, writer, config)
                except EOFError:
                    return
                except RequestError as exc:
                    version = "HTTP/1.1"
                    response = error_response(exc.status, exc.message)
                    data = serialize(response, version, keep_alive=False)
                    writer.write(data)
                    writer.flush()
                    self._log("-", "-", exc.status, 0.0)
                    return

                request.remote_addr = addr
                started = time.monotonic()
                response = self._safe_dispatch(request)
                elapsed_ms = (time.monotonic() - started) * 1000

                forced = (response.get_header("Connection") or "").lower()
                keep_alive = request.keep_alive and forced != "close"
                is_head = request.method == "HEAD"

                try:
                    writer.write(serialize(
                        response,
                        request.version,
                        keep_alive=keep_alive,
                        include_body=not is_head,
                    ))
                    writer.flush()
                except OSError:
                    return

                self._log(
                    request.method,
                    request.target,
                    response.status,
                    elapsed_ms,
                )
                if not keep_alive:
                    return
        except (OSError, ConnectionError):
            return
        finally:
            self._close_quietly(reader, writer, sock)

    @staticmethod
    def _close_quietly(reader, writer, sock=None) -> None:
        # makefile() wraps the socket in a SocketIO with a duplicated
        # fd; shut the raw socket down so the peer receives FIN promptly.
        if sock is not None:
            try:
                sock.shutdown(__import__("socket").SHUT_WR)
            except OSError:
                pass
        for obj in (writer, reader):
            try:
                obj.close()
            except Exception:
                pass

    def _log_client_open(self, addr) -> None:
        return

    def _log(self, method: str, target: str, status: int, elapsed_ms: float) -> None:
        if self.logger is None:
            return
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        self.logger(
            "%s %s %s %d %.2fms" % (stamp, method, target, status, elapsed_ms)
        )
