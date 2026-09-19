"""The staging area (.minigit/index).

Format: one text record per line, sorted by path for reproducibility:

    <mode> <blob-sha1> <path>\n

Paths may contain spaces (they are stored last on the line); newlines in
file names are not supported.
"""

import os

from . import objects


class IndexEntry(object):
    __slots__ = ("mode", "oid", "path")

    def __init__(self, mode, oid, path):
        self.mode = mode
        self.oid = oid
        self.path = path

    def __repr__(self):
        return "IndexEntry(%r, %r, %r)" % (self.mode, self.oid, self.path)

    def __eq__(self, other):
        return (isinstance(other, IndexEntry)
                and (self.mode, self.oid, self.path)
                == (other.mode, other.oid, other.path))

    def __hash__(self):
        return hash((self.mode, self.oid, self.path))


def read_index(repo):
    """Return an ordered dict-like {path: IndexEntry} sorted by path."""
    entries = {}
    if not os.path.exists(repo.index_file):
        return entries
    with open(repo.index_file, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line:
                continue
            mode, oid, path = line.split(" ", 2)
            entries[path] = IndexEntry(mode, oid, path)
    return entries


def write_index(repo, entries):
    """Persist {path: IndexEntry} in a stable, sorted text format."""
    lines = []
    for path in sorted(entries):
        entry = entries[path]
        lines.append("%s %s %s\n" % (entry.mode, entry.oid, entry.path))
    tmp = repo.index_file + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.writelines(lines)
    os.replace(tmp, repo.index_file)


def build_tree(repo, entries, prefix=""):
    """Recursively build (and store) tree objects from index entries.

    *entries* maps full repo-relative paths to IndexEntry; *prefix* is the
    directory currently being built.  Returns the root tree hash.
    """
    tree_entries = []
    subdirs = {}
    for path in sorted(entries):
        if not path.startswith(prefix):
            continue
        rest = path[len(prefix):]
        if "/" in rest:
            subdirs.setdefault(rest.split("/", 1)[0], True)
        else:
            entry = entries[path]
            tree_entries.append(objects.TreeEntry(entry.mode, rest, entry.oid))
    for dirname in sorted(subdirs):
        sub_oid = build_tree(repo, entries, prefix + dirname + "/")
        tree_entries.append(objects.TreeEntry(objects.MODE_TREE, dirname, sub_oid))
    return objects.write_object(repo, objects.TREE, objects.serialize_tree(tree_entries))
