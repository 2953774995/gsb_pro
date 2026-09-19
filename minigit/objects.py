"""Content-addressed object store (blob / tree / commit).

Object identity is the SHA-1 of "<type> <length>\\0<payload>" (the same
framing Git uses).  Objects are zlib-compressed and stored under
.minigit/objects/<first-2-hex>/<remaining-38-hex>.
"""

import hashlib
import os
import zlib

from .errors import MiniGitError

BLOB = "blob"
TREE = "tree"
COMMIT = "commit"

OBJ_TYPES = (BLOB, TREE, COMMIT)

# File modes recorded in trees / the index.
MODE_FILE = "100644"
MODE_EXEC = "100755"
MODE_TREE = "40000"


def hash_object(obj_type, data):
    """Return the SHA-1 hex digest that identifies this object."""
    if obj_type not in OBJ_TYPES:
        raise MiniGitError("fatal: unknown object type: %r" % obj_type)
    if isinstance(data, str):
        data = data.encode("utf-8")
    header = ("%s %d\0" % (obj_type, len(data))).encode("utf-8")
    return hashlib.sha1(header + data).hexdigest()


def _object_path(repo, oid):
    return os.path.join(repo.objects_dir, oid[:2], oid[2:])


def write_object(repo, obj_type, data):
    """Store *data* as an object of *obj_type*; return its hash.

    Identical content is stored exactly once (content addressing gives
    deduplication for free).
    """
    if isinstance(data, str):
        data = data.encode("utf-8")
    oid = hash_object(obj_type, data)
    path = _object_path(repo, oid)
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp%d" % os.getpid()
        with open(tmp, "wb") as fh:
            fh.write(zlib.compress(("%s %d\0" % (obj_type, len(data))).encode("utf-8") + data))
        os.replace(tmp, path)
    return oid


def read_object(repo, oid):
    """Return (obj_type, payload_bytes) for *oid* (full 40-char hash)."""
    path = _object_path(repo, oid)
    if not os.path.exists(path):
        raise MiniGitError("fatal: object not found: %s" % oid)
    with open(path, "rb") as fh:
        raw = zlib.decompress(fh.read())
    header, _, data = raw.partition(b"\0")
    obj_type, _, _size = header.decode("utf-8").partition(" ")
    return obj_type, data


def object_exists(repo, oid):
    return os.path.exists(_object_path(repo, oid))


def find_object(repo, prefix):
    """Resolve a (possibly abbreviated) hex prefix to a full object id."""
    if len(prefix) == 40 and object_exists(repo, prefix):
        return prefix
    if len(prefix) < 4:
        raise MiniGitError("fatal: ambiguous object prefix too short: %s" % prefix)
    matches = []
    fanout = os.path.join(repo.objects_dir, prefix[:2])
    if os.path.isdir(fanout):
        for name in os.listdir(fanout):
            full = prefix[:2] + name
            if full.startswith(prefix):
                matches.append(full)
    if not matches:
        raise MiniGitError("fatal: not a valid object name: %s" % prefix)
    if len(matches) > 1:
        raise MiniGitError("fatal: ambiguous object prefix: %s" % prefix)
    return matches[0]


# ---------------------------------------------------------------------------
# Trees
# ---------------------------------------------------------------------------

class TreeEntry(object):
    """One (mode, name, hash) triple inside a tree object."""

    __slots__ = ("mode", "name", "oid")

    def __init__(self, mode, name, oid):
        self.mode = mode
        self.name = name
        self.oid = oid

    @property
    def is_tree(self):
        return self.mode == MODE_TREE

    def sort_key(self):
        # Git-compatible deterministic ordering: directories sort as "name/".
        return self.name + "/" if self.is_tree else self.name

    def __repr__(self):
        return "TreeEntry(%r, %r, %r)" % (self.mode, self.name, self.oid)


def serialize_tree(entries):
    """Serialize tree entries to the canonical binary payload."""
    out = bytearray()
    for entry in sorted(entries, key=lambda e: e.sort_key()):
        out += ("%s %s\0" % (entry.mode, entry.name)).encode("utf-8")
        out += bytes.fromhex(entry.oid)
    return bytes(out)


def parse_tree(data):
    """Parse a tree payload back into a list of TreeEntry."""
    entries = []
    i = 0
    while i < len(data):
        sp = data.index(b" ", i)
        mode = data[i:sp].decode("ascii")
        nul = data.index(b"\0", sp)
        name = data[sp + 1:nul].decode("utf-8")
        oid = data[nul + 1:nul + 21].hex()
        entries.append(TreeEntry(mode, name, oid))
        i = nul + 21
    return entries


def read_tree(repo, tree_oid):
    obj_type, data = read_object(repo, tree_oid)
    if obj_type != TREE:
        raise MiniGitError("fatal: object %s is not a tree" % tree_oid)
    return parse_tree(data)


def flatten_tree(repo, tree_oid, prefix=""):
    """Expand a tree object into {path: (mode, blob_oid)} recursively."""
    result = {}
    for entry in read_tree(repo, tree_oid):
        path = prefix + entry.name
        if entry.is_tree:
            result.update(flatten_tree(repo, entry.oid, path + "/"))
        else:
            result[path] = (entry.mode, entry.oid)
    return result
