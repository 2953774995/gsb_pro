"""Static file serving with directory-traversal protection."""

import os

from .errors import HTTPError

#: Built-in MIME table (common types only).
MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".csv": "text/csv; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".mjs": "application/javascript; charset=utf-8",
    ".json": "application/json",
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
    ".gz": "application/gzip",
    ".tar": "application/x-tar",
    ".mp3": "audio/mpeg",
    ".mp4": "video/mp4",
    ".wasm": "application/wasm",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
}

DEFAULT_MIME = "application/octet-stream"


def guess_type(path):
    ext = os.path.splitext(path)[1].lower()
    return MIME_TYPES.get(ext, DEFAULT_MIME)


class StaticFiles(object):
    """Serves files from a root directory.

    Security hard rule: the normalized, absolute real path of every
    served file must stay inside the root.  Any ``../`` or
    percent-encoded traversal attempt results in 404.
    """

    def __init__(self, root, index="index.html"):
        self.root = os.path.realpath(os.path.abspath(root))
        self.index = index

    def resolve(self, url_path):
        """Map a decoded URL path to a filesystem path, or None."""
        if "\x00" in url_path:
            return None
        rel = url_path.lstrip("/")
        candidate = os.path.realpath(os.path.join(self.root, rel))
        try:
            if os.path.commonpath([candidate, self.root]) != self.root:
                return None
        except ValueError:
            return None
        return candidate

    def handle(self, request):
        """Return (status, headers, body) for a static request."""
        if request.method not in ("GET", "HEAD"):
            raise HTTPError(405, "method not allowed",
                            headers=[("Allow", "GET, HEAD")])
        path = self.resolve(request.path)
        if path is None:
            raise HTTPError(404, "not found")
        if os.path.isdir(path):
            index = os.path.join(path, self.index)
            if os.path.isfile(index):
                path = index
            else:
                raise HTTPError(403, "directory listing is forbidden")
        if not os.path.isfile(path):
            raise HTTPError(404, "not found")
        try:
            with open(path, "rb") as fh:
                body = fh.read()
        except OSError:
            raise HTTPError(404, "not found")
        headers = [("Content-Type", guess_type(path))]
        return 200, headers, body
