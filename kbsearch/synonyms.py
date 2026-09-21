"""Synonym table support.

File format: one group per line, entries separated by ``=`` (``,`` and
``，`` are also accepted). Blank lines and ``#`` comments are ignored::

    冰箱=冰柜=冷藏柜
    维修=修理
    fridge=refrigerator

Both Chinese and English entries are supported. Entries are matched against
the *raw* query word (ASCII case-insensitively); expansion happens before
tokenization, so multi-character Chinese entries work naturally.
"""

import re

_SPLIT_RE = re.compile(r"[=,，]")


def _norm(word):
    w = word.strip()
    return w.lower() if w.isascii() else w


class SynonymMap:
    def __init__(self):
        # normalized raw entry -> frozenset of the whole group (normalized)
        self._groups = {}

    @classmethod
    def from_file(cls, path):
        smap = cls()
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = [_norm(p) for p in _SPLIT_RE.split(line)]
                parts = [p for p in parts if p]
                if len(parts) < 2:
                    continue
                smap.add_group(parts)
        return smap

    def add_group(self, words):
        group = frozenset(_norm(w) for w in words if w.strip())
        if len(group) < 2:
            return
        for w in group:
            self._groups[w] = group

    def expand(self, raw):
        """Return all raw variants for *raw* (including itself)."""
        key = _norm(raw)
        group = self._groups.get(key)
        if group is None:
            return [raw]
        return sorted(group)

    def __len__(self):
        return len(self._groups)
