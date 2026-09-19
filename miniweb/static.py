"""Static file serving with MIME table and directory-traversal protection."""

import os

from .errors import Forbidden, MethodNotAllowed, NotFound
from .response import Response

MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json",
    ".txt": "text/plain; charset=utf-8",
    ".xml": "application/xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".webp": "image/webp",
    ".pdf": "application/pdf",
    ".zip": "application/zip",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".mp3": "audio/mpeg",
    ".mp4": "video/mp4",
}

DEFAULT_MIME = "application/octet-stream"


def guess_type(path):
    ext = os.path.splitext(path)[1].lower()
    return MIME_TYPES.get(ext, DEFAULT_MIME)


class StaticFiles:
    """Serves files from a root directory, confined to that root."""

    def __init__(self, root):
        self.root = os.path.realpath(root)

    def resolve(self, url_path):
        """Map a URL path to a filesystem path inside the root.

        Any attempt to escape the root (via ../ or encoded variants, which
        have already been percent-decoded by the request parser) yields None.
        """
        normalized = os.path.normpath("/" + url_path).lstrip("/")
        candidate = os.path.realpath(os.path.join(self.root, normalized))
        if candidate != self.root and not candidate.startswith(self.root + os.sep):
            return None
        return candidate

    def handle(self, request):
        if request.method not in ("GET", "HEAD"):
            raise MethodNotAllowed(["GET", "HEAD"])
        path = self.resolve(request.path)
        if path is None:
            raise NotFound("not found")
        if os.path.isdir(path):
            index = os.path.join(path, "index.html")
            if os.path.isfile(index):
                path = index
            else:
                raise Forbidden("directory listing is disabled")
        if not os.path.isfile(path):
            raise NotFound("not found")
        try:
            with open(path, "rb") as f:
                body = f.read()
        except OSError:
            raise NotFound("not found")
        return Response(200, {"Content-Type": guess_type(path)}, body)
