"""Static file serving with strict directory-traversal protection."""

import os
import posixpath
from urllib.parse import unquote

from .errors import HTTPError
from .response import Response

# Small built-in MIME table (no third-party packages involved).
MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".xml": "application/xml",
    ".csv": "text/csv; charset=utf-8",
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
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".mp3": "audio/mpeg",
    ".mp4": "video/mp4",
    ".wasm": "application/wasm",
}
DEFAULT_MIME = "application/octet-stream"


def guess_mime(path: str) -> str:
    return MIME_TYPES.get(os.path.splitext(path)[1].lower(), DEFAULT_MIME)


def serve_static(root: str, url_path: str, head: bool = False) -> Response:
    """Resolve ``url_path`` under ``root`` and return a file response.

    Traversal attempts (``..`` segments, encoded ``%2e%2e``, backslash
    tricks, symlinks pointing outside the root) all surface as 404 so
    the filesystem layout is never revealed.
    """
    root = os.path.realpath(root)

    # Decode each path segment and reject anything that becomes "..".
    clean_segments = []
    for segment in url_path.split("/"):
        decoded = unquote(segment)
        # Backslash is not a POSIX separator, but normalize it away so
        # Windows-style payloads cannot confuse later checks either.
        decoded = decoded.replace("\\", "/")
        for piece in decoded.split("/"):
            if piece in ("", "."):
                continue
            if piece == "..":
                raise HTTPError(404)
            clean_segments.append(piece)

    relative = posixpath.sep.join(clean_segments)
    absolute = os.path.realpath(os.path.join(root, relative))

    # Defense in depth: the resolved path MUST live inside the root.
    if os.path.commonpath([root, absolute]) != root:
        raise HTTPError(404)

    if os.path.isdir(absolute):
        if not url_path.endswith("/"):
            # Redirect /dir -> /dir/ so relative links keep working.
            raise HTTPError(301, headers={"Location": url_path + "/"})
        index_path = os.path.join(absolute, "index.html")
        if os.path.isfile(index_path):
            absolute = index_path
        else:
            # Directory exists but has no index page: listing is denied.
            raise HTTPError(403)

    if not os.path.isfile(absolute):
        raise HTTPError(404)

    try:
        with open(absolute, "rb") as handle:
            data = handle.read()
    except OSError:
        raise HTTPError(404)

    return Response(
        status=200,
        headers=[
            ("Content-Type", guess_mime(absolute)),
            ("Content-Length", str(len(data))),
        ],
        body=b"" if head else data,
    )
