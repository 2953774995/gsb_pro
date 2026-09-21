"""Static file serving with strict root containment."""

import os
import posixpath
from pathlib import Path

from .errors import HTTPError

MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".ico": "image/x-icon",
    ".webp": "image/webp",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".pdf": "application/pdf",
    ".csv": "text/csv; charset=utf-8",
    ".xml": "application/xml; charset=utf-8",
}


def guess_mime(path):
    return MIME_TYPES.get(Path(path).suffix.lower(), "application/octet-stream")


class StaticFileServer:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def _safe_path(self, url_path):
        if "\x00" in url_path or any(ord(c) < 32 or ord(c) == 127 for c in url_path):
            raise HTTPError(404, "Not Found")
        segments = [segment for segment in url_path.split("/") if segment not in ("", ".")]
        if any(segment == ".." for segment in segments):
            raise HTTPError(404, "Not Found")
        candidate = (self.root / posixpath.normpath(url_path).lstrip("/")).resolve()
        try:
            if os.path.commonpath([str(self.root), str(candidate)]) != str(self.root):
                raise HTTPError(404, "Not Found")
        except ValueError as exc:
            raise HTTPError(404, "Not Found") from exc
        return candidate

    @staticmethod
    def _read_file(path):
        try:
            if path.is_symlink() or not path.is_file():
                raise HTTPError(404, "Not Found")
            data = path.read_bytes()
        except FileNotFoundError as exc:
            raise HTTPError(404, "Not Found") from exc
        except PermissionError as exc:
            raise HTTPError(403, "Forbidden") from exc
        except OSError as exc:
            raise HTTPError(404, "Not Found") from exc
        return 200, {"Content-Type": guess_mime(path), "Accept-Ranges": "bytes"}, data

    def serve(self, request):
        path = self._safe_path(request.path)
        try:
            is_dir = path.is_dir()
            exists = path.exists()
        except PermissionError as exc:
            raise HTTPError(403, "Forbidden") from exc
        except OSError as exc:
            raise HTTPError(404, "Not Found") from exc

        if is_dir:
            if not request.path.endswith("/"):
                raw_path, _, raw_query = request.target.partition("?")
                location = raw_path.rstrip("/") + "/"
                if raw_query:
                    location += "?" + raw_query
                raise HTTPError(301, "Moved Permanently", {"Location": location})
            index = path / "index.html"
            if index.is_file() and not index.is_symlink():
                return self._read_file(index)
            raise HTTPError(403, "Directory listing is forbidden")
        if not exists:
            raise HTTPError(404, "Not Found")
        return self._read_file(path)
