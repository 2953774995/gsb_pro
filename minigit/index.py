"""The staging index stored at ``.minigit/index``.

Binary format, fully stable and reproducible (entries sorted by path;
no timestamps, inodes or other host-specific data)::

    magic   = b"MIDX"
    version = uint16 big-endian          (currently 1)
    count   = uint32 big-endian
    count entries of:
        mode     = uint32 big-endian     (file mode, e.g. 100644)
        sha      = 20 raw SHA-1 bytes
        path_len = uint16 big-endian
        path     = path_len raw UTF-8 bytes

Identical staged content always serialises to identical index bytes.
"""

import os
import struct

MAGIC = b"MIDX"
VERSION = 1
_HEADER = struct.Struct(">4sHI")
_ENTRY_HEAD = struct.Struct(">I20sH")


class Index:
    """In-memory index: ``entries`` is ``{path: (mode:int, sha:str)}``."""

    def __init__(self, entries=None):
        self.entries = dict(entries) if entries else {}

    # ------------------------------------------------------------ serialising
    def to_bytes(self):
        chunks = [_HEADER.pack(MAGIC, VERSION, len(self.entries))]
        for path in sorted(self.entries):
            mode, sha = self.entries[path]
            path_bytes = path.encode("utf-8")
            chunks.append(
                _ENTRY_HEAD.pack(int(mode), bytes.fromhex(sha), len(path_bytes))
            )
            chunks.append(path_bytes)
        return b"".join(chunks)

    @classmethod
    def from_bytes(cls, data):
        idx = cls()
        if not data:
            return idx
        if len(data) < _HEADER.size:
            raise ValueError("corrupt index: truncated header")
        magic, version, count = _HEADER.unpack_from(data, 0)
        if magic != MAGIC:
            raise ValueError("corrupt index: bad magic %r" % magic)
        if version != VERSION:
            raise ValueError("unsupported index version: %d" % version)
        pos = _HEADER.size
        for _ in range(count):
            if pos + _ENTRY_HEAD.size > len(data):
                raise ValueError("corrupt index: truncated entry")
            mode, digest, path_len = _ENTRY_HEAD.unpack_from(data, pos)
            pos += _ENTRY_HEAD.size
            if pos + path_len > len(data):
                raise ValueError("corrupt index: truncated path")
            path = data[pos : pos + path_len].decode("utf-8")
            pos += path_len
            idx.entries[path] = (int(mode), digest.hex())
        return idx

    # ----------------------------------------------------------------- helpers
    def add(self, path, mode, sha):
        self.entries[path] = (int(mode), sha)

    def remove(self, path):
        self.entries.pop(path, None)

    def paths(self):
        return set(self.entries)

    def get(self, path):
        return self.entries.get(path)

    def __contains__(self, path):
        return path in self.entries

    def __len__(self):
        return len(self.entries)


def load_index(repo):
    """Load the index; an absent index file is an empty index."""
    try:
        with open(repo.index_file, "rb") as fh:
            return Index.from_bytes(fh.read())
    except FileNotFoundError:
        return Index()


def save_index(repo, index):
    tmp = repo.index_file + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(index.to_bytes())
    os.replace(tmp, repo.index_file)
