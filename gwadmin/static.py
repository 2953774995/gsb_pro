"""Static file serving with MIME detection and traversal protection."""

import os
import posixpath

from .http import HTTPError

MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".mjs": "application/javascript; charset=utf-8",
    ".json": "application/json",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".webp": "image/webp",
    ".txt": "text/plain; charset=utf-8",
    ".xml": "application/xml",
    ".pdf": "application/pdf",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".wasm": "application/wasm",
    ".map": "application/json",
    ".csv": "text/csv; charset=utf-8",
    ".mp4": "video/mp4",
}
DEFAULT_MIME = "application/octet-stream"


def guess_mime(path):
    ext = os.path.splitext(path)[1].lower()
    return MIME_TYPES.get(ext, DEFAULT_MIME)


class StaticFiles(object):
    """Serves files from a root directory.

    Security: the request path is normalized and must resolve inside the
    root; any '..' or encoded traversal attempt yields 404.
    """

    def __init__(self, root, index="index.html", allow_listing=False):
        self.root = os.path.realpath(root)
        self.index = index
        self.allow_listing = allow_listing

    def resolve(self, url_path):
        """Map a decoded URL path to a filesystem path, or None if the
        path escapes the root."""
        # Hard rule: any '..' segment (already percent-decoded) is a
        # traversal attempt -> reject outright.
        segments = url_path.split("/")
        if any(seg == ".." for seg in segments):
            return None
        # Normalize as a POSIX path (URL semantics), dropping '.' segments.
        normalized = posixpath.normpath(url_path)
        if normalized.startswith(".."):
            return None
        rel = normalized.lstrip("/")
        candidate = os.path.realpath(os.path.join(self.root, rel))
        if candidate != self.root and \
                not candidate.startswith(self.root + os.sep):
            return None
        return candidate

    def serve(self, url_path):
        """Return (status, headers, body) for a decoded URL path."""
        fs_path = self.resolve(url_path)
        if fs_path is None:
            raise HTTPError(404, "Not Found")
        if os.path.isdir(fs_path):
            index_path = os.path.join(fs_path, self.index)
            if os.path.isfile(index_path):
                fs_path = index_path
            elif self.allow_listing:
                return self._listing(fs_path, url_path)
            else:
                raise HTTPError(403, "directory listing is disabled")
        if not os.path.isfile(fs_path):
            raise HTTPError(404, "Not Found")
        try:
            with open(fs_path, "rb") as fh:
                body = fh.read()
        except OSError:
            raise HTTPError(404, "Not Found")
        headers = [("Content-Type", guess_mime(fs_path))]
        return 200, headers, body

    def _listing(self, fs_path, url_path):
        entries = sorted(os.listdir(fs_path))
        items = "".join(
            '<li><a href="{0}{1}">{1}{2}</a></li>'.format(
                url_path.rstrip("/") + "/", name,
                "/" if os.path.isdir(os.path.join(fs_path, name)) else "")
            for name in entries)
        body = ("<!DOCTYPE html><html><body><h1>Index of %s</h1>"
                "<ul>%s</ul></body></html>" % (url_path, items))
        return 200, [("Content-Type", "text/html; charset=utf-8")], body
