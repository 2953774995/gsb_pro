"""Configurable synonym groups."""
from __future__ import annotations

from typing import Dict, Iterable, List, Sequence, Tuple

from .tokenizer import Analyzer


class SynonymStore:
    """Stores equivalence groups such as ``冰箱=冰柜=冷藏柜``.

    Variants are normalized with the same analyzer used by the index.  A
    variant can consist of one English stem or one/more Chinese characters.
    """

    def __init__(self, analyzer: Analyzer) -> None:
        self.analyzer = analyzer
        self._groups: List[List[Tuple[str, ...]]] = []
        self._lookup: Dict[Tuple[str, ...], int] = {}

    @staticmethod
    def variant_key(terms: Sequence[str]) -> Tuple[str, ...]:
        return tuple(terms)

    def normalize_text(self, text: str) -> Tuple[str, ...]:
        return tuple(token.term for token in self.analyzer.analyze(text))

    def add_group(self, words: Iterable[str]) -> None:
        return self.add_group_with_id(words, None)

    def add_group_with_id(self, words: Iterable[str], stable_id):
        variants = []
        seen = set()
        for word in words:
            terms = self.normalize_text(str(word).strip())
            if not terms:
                continue
            key = self.variant_key(terms)
            if key not in seen:
                seen.add(key)
                variants.append(key)
        if len(variants) <= 1:
            # A one-member group is harmless but provides no expansion.
            if variants and variants[0] not in self._lookup:
                group_id = stable_id if stable_id is not None else len(self._groups)
                self._groups.append(variants)
                self._lookup[variants[0]] = group_id
            return self._lookup[variants[0]] if variants else None

        # Merge with any groups that share an existing variant, preserving the
        # transitive meaning of repeated configuration lines.
        existing_ids = []
        merged = list(variants)
        merged_seen = set(merged)
        for variant in variants:
            old_id = self._lookup.get(variant)
            if old_id is not None and old_id not in existing_ids:
                existing_ids.append(old_id)
                for old_variant in self._groups[old_id]:
                    if old_variant not in merged_seen:
                        merged_seen.add(old_variant)
                        merged.append(old_variant)

        if stable_id is not None and not existing_ids:
            # Pad when using an externally stable integer id (loaded groups).
            while len(self._groups) <= stable_id:
                self._groups.append([])
            new_id = stable_id
        elif existing_ids:
            new_id = existing_ids[0]
        else:
            new_id = len(self._groups)
        if new_id == len(self._groups):
            self._groups.append(merged)
        else:
            self._groups[new_id] = merged
        for variant in merged:
            self._lookup[variant] = new_id
        for old_id in existing_ids[1:]:
            # Leave an empty tombstone; all variants now point to the merger.
            self._groups[old_id] = []
        return new_id

    def lookup(self, terms: Sequence[str]):
        return self.get_group(terms)[1]

    def get_group(self, terms: Sequence[str]):
        group_id = self._lookup.get(tuple(terms))
        if group_id is None:
            return None, None
        group = self._groups[group_id]
        return (group_id, group) if group else (None, None)

    def load_lines(self, lines: Iterable[str]) -> None:
        for raw in lines:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = [part.strip() for part in line.split("=")]
            if any(part for part in parts):
                self.add_group(parts)

    def load_file(self, path: str) -> None:
        with open(path, "r", encoding="utf-8") as handle:
            self.load_lines(handle)

    def to_dict(self) -> dict:
        return {"groups": [list(group) for group in self._groups if group]}

    @classmethod
    def from_dict(cls, data: dict, analyzer: Analyzer) -> "SynonymStore":
        store = cls(analyzer)
        for group in data.get("groups", []):
            variants = [tuple(terms) for terms in group if terms]
            if not variants:
                continue
            group_id = len(store._groups)
            store._groups.append(variants)
            for variant in variants:
                store._lookup[variant] = group_id
        return store
