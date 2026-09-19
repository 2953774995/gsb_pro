"""Object store: blob / tree / commit, SHA-1 content addressing, zlib.

Object format (identical in spirit to git's loose objects)::

    <type> SP <decimal byte length of body> NUL <body bytes>

The whole frame is SHA-1 hashed (that hash is the object id) and stored
zlib-compressed at ``.minigit/objects/<2>/<38>``.

Tree bodies concatenate one record per entry::

    "<mode> <name>" NUL <raw 20-byte sha-1 digest>

Directory entries carry a trailing ``/`` in *names used only for
sorting* so that, like git, ``foo`` and ``foo/bar`` are ordered
deterministically (``foo`` sorts before ``foo.bar`` but a directory
``foo`` sorts after ``foo.bar``).
"""

import hashlib
import os
import time
import zlib

from .errors import ObjectNotFoundError

VALID_TYPES = ("blob", "tree", "commit")


# ----------------------------------------------------------------- low level
def _frame(obj_type, body):
    if obj_type not in VALID_TYPES:
        raise ValueError("unknown object type: %r" % (obj_type,))
    return obj_type.encode("ascii") + b" " + str(len(body)).encode("ascii") + b"\x00" + body


def hash_object(obj_type, data):
    """Return the SHA-1 id (40 hex chars) of ``(type, data)``."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha1(_frame(obj_type, data)).hexdigest()


def write_object(repo, obj_type, data):
    """Hash, store (idempotent / deduplicating) and return the object id."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    payload = _frame(obj_type, data)
    sha = hashlib.sha1(payload).hexdigest()
    path = repo.object_path(sha)
    if not os.path.exists(path):  # identical content -> same object, stored once
        os.makedirs(os.path.dirname(path), exist_ok=True)
        compressed = zlib.compress(payload, level=6)
        tmp = path + ".tmp"
        with open(tmp, "wb") as fh:
            fh.write(compressed)
        os.replace(tmp, path)
    return sha


def read_object(repo, sha):
    """Read object ``sha``; return ``(type, data_bytes)``."""
    path = repo.object_path(sha)
    if not os.path.exists(path):
        raise ObjectNotFoundError(
            "fatal: object %s not found" % (sha[:12] if len(sha) >= 12 else sha)
        )
    with open(path, "rb") as fh:
        raw = zlib.decompress(fh.read())
    nul = raw.index(b"\x00")
    header = raw[:nul].decode("ascii")
    obj_type, length = header.split(" ")
    body = raw[nul + 1 :]
    if len(body) != int(length):
        raise ObjectNotFoundError("fatal: corrupt object %s (bad length)" % sha[:12])
    return obj_type, body


def object_exists(repo, sha):
    return len(sha) == 40 and os.path.exists(repo.object_path(sha))


# ------------------------------------------------------------------- blob API
def write_blob(repo, data):
    return write_object(repo, "blob", data)


def read_blob(repo, sha):
    obj_type, body = read_object(repo, sha)
    if obj_type != "blob":
        raise ObjectNotFoundError("fatal: %s is not a blob" % sha[:12])
    return body


# ------------------------------------------------------------------- tree API
def _tree_sort_key(name, is_dir):
    """Git-compatible sort key: directories are compared as ``name + '/'``."""
    if is_dir:
        return name + "/"
    return name


def build_tree(repo, entries):
    """Recursively build tree objects from a flat mapping of file paths.

    :param entries: mapping ``"dir/file" -> (mode, blob_sha)`` where mode
        is an int (``100644`` / ``100755``).
    :returns: sha of the root tree.
    """
    # Group the flat path space into nested directory tables.
    root = {}
    for path, (mode, sha) in entries.items():
        parts = [p for p in path.split("/") if p]
        node = root
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        if not isinstance(node, dict):
            raise ValueError("path conflicts with existing file: %s" % path)
        node[parts[-1]] = ("file", int(mode), sha)

    def write_node(table):
        records = []
        for name, value in table.items():
            if isinstance(value, dict):
                child_sha = write_node(value)
                records.append((_tree_sort_key(name, True), b"40000", name, child_sha))
            else:
                _, mode, blob_sha = value
                records.append(
                    (_tree_sort_key(name, False), ("%o" % mode).encode("ascii"), name, blob_sha)
                )
        records.sort(key=lambda rec: rec[0])
        body = b""
        for _key, mode_bytes, name, sha in records:
            body += mode_bytes + b" " + name.encode("utf-8") + b"\x00" + bytes.fromhex(sha)
        return write_object(repo, "tree", body)

    return write_node(root)


def parse_tree(body):
    """Parse tree body bytes into ``[(mode:int, name:str, sha:str, is_dir)]``."""
    out = []
    i = 0
    while i < len(body):
        sp = body.index(b" ", i)
        mode = body[i:sp].decode("ascii")
        nul = body.index(b"\x00", sp)
        name = body[sp + 1 : nul].decode("utf-8")
        digest = body[nul + 1 : nul + 21]
        if len(digest) != 20:
            raise ValueError("truncated tree object")
        is_dir = mode == "40000"
        out.append((int(mode, 8), name, digest.hex(), is_dir))
        i = nul + 21
    return out


def read_tree(repo, sha):
    if sha is None:
        return []
    obj_type, body = read_object(repo, sha)
    if obj_type != "tree":
        raise ObjectNotFoundError("fatal: %s is not a tree" % sha[:12])
    return parse_tree(body)


def flatten_tree(repo, tree_sha, prefix=""):
    """Flatten a tree to ``{path: (mode, sha)}`` for every contained blob."""
    result = {}
    if tree_sha is None:
        return result
    for mode, name, sha, is_dir in read_tree(repo, tree_sha):
        path = prefix + name
        if is_dir:
            result.update(flatten_tree(repo, sha, path + "/"))
        else:
            result[path] = (mode, sha)
    return result


# ----------------------------------------------------------------- commit API
def _git_time(timestamp=None):
    if timestamp is None:
        timestamp = int(time.time())
    if time.daylight and time.localtime(timestamp).tm_isdst:
        offset_sec = -time.altzone
    else:
        offset_sec = -time.timezone
    sign = "+" if offset_sec >= 0 else "-"
    off = abs(offset_sec)
    return "%d %s%02d%02d" % (timestamp, sign, off // 3600, off % 3600 // 60)


def make_commit_body(tree_sha, parent_shas, author, email, message, timestamp=None):
    """Build commit body bytes."""
    lines = ["tree %s" % tree_sha]
    for parent in parent_shas:
        lines.append("parent %s" % parent)
    stamp = _git_time(timestamp)
    lines.append("author %s <%s> %s" % (author, email, stamp))
    lines.append("committer %s <%s> %s" % (author, email, stamp))
    body = "\n".join(lines) + "\n\n" + message.rstrip("\n") + "\n"
    return body.encode("utf-8")


def write_commit(repo, tree_sha, parent_shas, author, email, message, timestamp=None):
    body = make_commit_body(tree_sha, parent_shas, author, email, message, timestamp)
    return write_object(repo, "commit", body)


def parse_commit(body):
    """Parse commit body into a dict (tree, parents, author, message, ...)."""
    if isinstance(body, bytes):
        text = body.decode("utf-8")
    else:
        text = body
    head, _, message = text.partition("\n\n")
    info = {"parents": [], "message": message.rstrip("\n"), "raw": text}
    for line in head.split("\n"):
        if not line:
            continue
        key, _, value = line.partition(" ")
        if key == "tree":
            info["tree"] = value
        elif key == "parent":
            info["parents"].append(value)
        elif key == "author":
            info["author"] = value
        elif key == "committer":
            info["committer"] = value
    return info


def read_commit(repo, sha):
    obj_type, body = read_object(repo, sha)
    if obj_type != "commit":
        raise ObjectNotFoundError("fatal: %s is not a commit" % sha[:12])
    return parse_commit(body)
