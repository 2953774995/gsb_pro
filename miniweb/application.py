"""Application object: router, middleware hooks, static files, error conversion."""

from __future__ import annotations

import logging
from typing import Callable, List, Optional

from .errors import HTTPError, InternalServerError, NotFound
from .request import Request
from .response import Response, make_error_response
from .router import Router
from .static import StaticFiles

BeforeHook = Callable[[Request], Optional[object]]
AfterHook = Callable[[Request, Response], Optional[Response]]
logger = logging.getLogger("miniweb")


class Application:
    def __init__(
        self,
        router: Optional[Router] = None,
        static_root: Optional[str] = None,
        before_hooks: Optional[List[BeforeHook]] = None,
        after_hooks: Optional[List[AfterHook]] = None,
        server_name: str = "miniweb",
    ) -> None:
        self.router = router or Router()
        self.static = StaticFiles(static_root) if static_root else None
        self.before_hooks = list(before_hooks or [])
        self.after_hooks = list(after_hooks or [])
        self.server_name = server_name

    def before_request(self, func: BeforeHook) -> BeforeHook:
        self.before_hooks.append(func)
        return func

    def after_request(self, func: AfterHook) -> AfterHook:
        self.after_hooks.append(func)
        return func

    def handle(
        self,
        request: Request,
        keep_alive: bool,
    ) -> Response:
        head = request.method == "HEAD"
        try:
            result = None
            for hook in self.before_hooks:
                shortcut = hook(request)
                if shortcut is not None:
                    result = shortcut
                    break

            if result is None:
                try:
                    handler, params = self.router.match(request.method, request.path)
                except HTTPError as routing_error:
                    if self.static is not None and isinstance(routing_error, NotFound):
                        # Only a router miss falls through to static serving; a
                        # method mismatch on a registered route remains 405.
                        result = self.static.serve(request.path, request.method)
                    else:
                        raise
                else:
                    request.params = params
                    result = handler(request)

            response = Response.from_handler(
                result,
                head=head,
                version=request.version,
                keep_alive=keep_alive,
                server_name=self.server_name,
            )
            for hook in self.after_hooks:
                replacement = hook(request, response)
                if replacement is not None:
                    response = Response.from_handler(
                        replacement,
                        head=head,
                        version=request.version,
                        keep_alive=keep_alive,
                        server_name=self.server_name,
                    )
            return response
        except HTTPError as error:
            return make_error_response(error, head=head)
        except Exception:  # security boundary: never leak a traceback/body.
            logger.exception("Unhandled application error")
            return make_error_response(InternalServerError(), head=head)
