"""Static file serving with conservative traversal protection."""

from __future__ import annotations

import mimetypes
import os
import posixpath
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import unquote

from .errors import Forbidden, InternalServerError, MethodNotAllowed, NotFound

# Explicit built-in table keeps MIME results predictable across platforms.
MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".csv": "text/csv; charset=utf-8",
    ".xml": "application/xml; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".webp": "image/webp",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".pdf": "application/pdf",
    ".zip": "application/zip",
    ".gz": "application/gzip",
}


def guess_mime(path: str) -> str:
    suffix = os.path.splitext(path)[1].lower()
    return MIME_TYPES.get(suffix) or mimetypes.guess_type(path)[0] or (
        "application/octet-stream"
    )


def contains_traversal(raw_url_path: str) -> bool:
    """Reject traversal-looking attempts before filesystem resolution.

    The check is intentionally conservative. It repeatedly percent-decodes
    the URL so both %2e%2e and double-encoded variants such as
    %252e%252e are rejected before touching the filesystem.
    """
    current = raw_url_path
    for _ in range(10):
        lowered = current.lower()
        # Encoded separators are always unsafe in a path handed to the
        # filesystem; encoded dots themselves are allowed (style%2Ecss).
        if "%2f" in lowered or "%5c" in lowered:
            return True
        decoded = unquote(current, errors="replace")
        if "\x00" in decoded or "\\" in decoded:
            return True
        segments = [seg for seg in decoded.split("/") if seg]
        for segment in segments:
            if segment in (".", "..") or ".." in segment:
                return True
        if decoded == current or "%" not in decoded:
            return False
        current = decoded
    return True


class StaticFiles:
    def __init__(self, root: str) -> None:
        self.root = Path(root).resolve(strict=False)
        if not self.root.exists() or not self.root.is_dir():
            raise ValueError(f"Static root does not exist or is not a directory: {root}")

    def resolve(self, url_path: str) -> Path:
        if contains_traversal(url_path):
            raise NotFound()

        decoded = unquote(url_path, errors="replace")
        # posixpath.normpath collapses internal double slashes.  At this point
        # any '..' or backslash has already been rejected.
        normalized = posixpath.normpath(decoded)
        if not normalized.startswith("/"):
            raise NotFound()
        relative = normalized.lstrip("/")
        candidate = (self.root / relative).resolve(strict=False)
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise NotFound() from exc
        return candidate

    def serve(
        self, url_path: str, method: str
    ) -> Tuple[int, dict, Optional[bytes]]:
        path = self.resolve(url_path)
        if not path.exists():
            raise NotFound()
        if path.is_dir():
            index = path / "index.html"
            if not index.is_file():
                if method not in ("GET", "HEAD"):
                    raise MethodNotAllowed("GET, HEAD")
                raise Forbidden("Directory index is forbidden")
            path = index
        if not path.is_file():
            raise NotFound()
        if method not in ("GET", "HEAD"):
            raise MethodNotAllowed("GET, HEAD")
        try:
            data = path.read_bytes()
        except PermissionError as exc:
            raise Forbidden("Permission denied") from exc
        except OSError as exc:
            raise InternalServerError("Unable to read static file") from exc
        headers = {"Content-Type": guess_mime(path.name)}
        return 200, headers, data
