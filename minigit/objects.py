"""Content-addressed object store (blob / tree / commit), Git-style.

Object on disk  = zlib("<type> <size>\\0" + payload)
Object id (sha) = sha1("<type> <size>\\0" + payload)
Stored at       = .minigit/objects/<sha[:2]>/<sha[2:]>
"""

import hashlib
import os
import re
import zlib

from .errors import MiniGitError

BLOB = "blob"
TREE = "tree"
COMMIT = "commit"

MODE_FILE = "100644"
MODE_EXEC = "100755"
MODE_DIR = "40000"


def hash_object(obj_type, data):
    """Return the SHA-1 id an object of ``obj_type`` with ``data`` would have."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    header = ("%s %d\0" % (obj_type, len(data))).encode("utf-8")
    return hashlib.sha1(header + data).hexdigest()


class ObjectStore:
    """Reads and writes zlib-compressed objects under .minigit/objects."""

    def __init__(self, gitdir):
        self.objects_dir = os.path.join(gitdir, "objects")

    def _path(self, sha):
        return os.path.join(self.objects_dir, sha[:2], sha[2:])

    def has_object(self, sha):
        return os.path.isfile(self._path(sha))

    def write_object(self, obj_type, data):
        """Write ``data`` as ``obj_type``; returns the SHA-1 id.

        Identical content is stored only once (content addressing).
        """
        if obj_type not in (BLOB, TREE, COMMIT):
            raise MiniGitError("unknown object type: %r" % obj_type)
        if isinstance(data, str):
            data = data.encode("utf-8")
        sha = hash_object(obj_type, data)
        path = self._path(sha)
        if not os.path.exists(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            payload = ("%s %d\0" % (obj_type, len(data))).encode("utf-8") + data
            tmp = path + ".tmp"
            with open(tmp, "wb") as fh:
                fh.write(zlib.compress(payload))
            os.replace(tmp, path)
        return sha

    def read_object(self, sha):
        """Return ``(obj_type, data_bytes)`` for ``sha``."""
        path = self._path(sha)
        if not os.path.isfile(path):
            raise MiniGitError("object not found: %s" % sha)
        with open(path, "rb") as fh:
            raw = zlib.decompress(fh.read())
        header, _, data = raw.partition(b"\0")
        obj_type, _, _size = header.partition(b" ")
        return obj_type.decode("ascii"), data


# ---------------------------------------------------------------------------
# tree objects
# ---------------------------------------------------------------------------

def encode_tree(entries):
    """Encode ``[(mode, name, sha), ...]`` (already sorted) into tree payload."""
    out = bytearray()
    for mode, name, sha in entries:
        out += ("%s %s\0" % (mode, name)).encode("utf-8")
        out += bytes.fromhex(sha)
    return bytes(out)


def decode_tree(data):
    """Decode a tree payload into ``[(mode, name, sha), ...]``."""
    entries = []
    i = 0
    while i < len(data):
        sp = data.index(b" ", i)
        mode = data[i:sp].decode("ascii")
        nul = data.index(b"\0", sp)
        name = data[sp + 1:nul].decode("utf-8")
        sha = data[nul + 1:nul + 21].hex()
        entries.append((mode, name, sha))
        i = nul + 21
    return entries


def _tree_sort_key(entry):
    mode, name, _sha = entry
    # Git sorts directories as if their name ended with '/'.
    return name + "/" if mode == MODE_DIR else name


def build_tree(store, entries):
    """Recursively write tree objects for ``{path: (mode, sha)}``; return root sha."""
    root = {}
    for path, (mode, sha) in entries.items():
        parts = path.split("/")
        node = root
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = (mode, sha)
    return _write_tree(store, root)


def _write_tree(store, node):
    items = []
    for name, value in node.items():
        if isinstance(value, dict):
            items.append((MODE_DIR, name, _write_tree(store, value)))
        else:
            mode, sha = value
            items.append((mode, name, sha))
    items.sort(key=_tree_sort_key)
    return store.write_object(TREE, encode_tree(items))


def flatten_tree(store, tree_sha, prefix=""):
    """Flatten a tree object into ``{path: (mode, sha)}``."""
    result = {}
    obj_type, data = store.read_object(tree_sha)
    if obj_type != TREE:
        raise MiniGitError("object %s is not a tree" % tree_sha)
    for mode, name, sha in decode_tree(data):
        path = prefix + name
        if mode == MODE_DIR:
            result.update(flatten_tree(store, sha, path + "/"))
        else:
            result[path] = (mode, sha)
    return result


# ---------------------------------------------------------------------------
# commit objects
# ---------------------------------------------------------------------------

def encode_commit(tree_sha, parents, author, committer, message):
    lines = ["tree %s" % tree_sha]
    lines += ["parent %s" % p for p in parents]
    lines.append("author %s" % author)
    lines.append("committer %s" % committer)
    body = "\n".join(lines) + "\n\n" + message
    if not body.endswith("\n"):
        body += "\n"
    return body.encode("utf-8")


def parse_commit(data):
    if isinstance(data, bytes):
        data = data.decode("utf-8")
    head, _, message = data.partition("\n\n")
    commit = {"tree": None, "parents": [], "author": "", "committer": "",
              "message": message}
    for line in head.splitlines():
        key, _, value = line.partition(" ")
        if key == "parent":
            commit["parents"].append(value)
        elif key in ("tree", "author", "committer"):
            commit[key] = value
    return commit


_IDENTITY_RE = re.compile(r"^(.*?) <(.*?)> (\d+) ([+-]\d{4})$")


def parse_identity(text):
    """Parse ``Name <email> <unix-ts> <tz>``; tolerant of malformed input."""
    m = _IDENTITY_RE.match(text or "")
    if not m:
        return text or "", "", 0, "+0000"
    return m.group(1), m.group(2), int(m.group(3)), m.group(4)
