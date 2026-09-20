"""High-level public API for kbsearch."""
from __future__ import annotations

import os
from typing import Dict, Iterable, List, Optional

from .index import InvertedIndex

from .parser import parse_query
from .persistence import load_index, save_index
from .query import QueryCompiler, QueryEvaluator, _EvalState
from .snippet import make_snippet
from .synonyms import SynonymStore
from .tokenizer import Analyzer


class KBSearch:
    """Offline after-sales knowledge-base search engine."""

    def __init__(self, use_stopwords: bool = True) -> None:
        self.analyzer = Analyzer(use_stopwords=use_stopwords)
        self.index = InvertedIndex(self.analyzer)
        self.synonyms = SynonymStore(self.analyzer)

    # ------------------------------------------------------------------
    # Document management
    # ------------------------------------------------------------------
    @staticmethod
    def _validate_doc_id(doc_id) -> None:
        if isinstance(doc_id, bool) or not isinstance(doc_id, (int, str)):
            raise TypeError("doc_id 必须是 int 或 str")
        if isinstance(doc_id, str) and not doc_id:
            raise ValueError("doc_id 不能为空字符串")

    def add_document(self, doc_id, text: str, title: str = "",
                     source: str = None) -> None:
        """Add or replace one document."""
        self._validate_doc_id(doc_id)
        if text is None:
            text = ""
        self.index.add_document(doc_id, str(text), title=title, source=source)

    def remove_document(self, doc_id) -> bool:
        """Remove one document and every posting that referenced it."""
        self._validate_doc_id(doc_id)
        return self.index.remove_document(doc_id)

    def document_count(self) -> int:
        return self.index.document_count()

    def get_document(self, doc_id) -> Optional[dict]:
        return self.index.get_record(doc_id)

    # ------------------------------------------------------------------
    # Synonyms
    # ------------------------------------------------------------------
    def add_synonym_group(self, words: Iterable[str]) -> None:
        self.synonyms.add_group(words)

    def load_synonyms(self, path: str) -> None:
        self.synonyms.load_file(path)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------
    def _compile(self, query: str):
        syntax = parse_query(query)
        return QueryCompiler(self.analyzer, self.synonyms).compile(syntax)

    def search(self, query: str, top_k: int = 10,
               with_snippet: bool = False) -> List[Dict]:
        """Return documents matching ``query`` ordered by descending score."""
        if top_k < 0:
            raise ValueError("top_k 不能为负数；0 表示返回全部结果")
        runtime = self._compile(query)
        evaluator = QueryEvaluator(self.index)
        state = _EvalState()
        universe = set(self.index.documents)
        matches = evaluator._docs(runtime, universe, state)
        if not matches:
            return []

        scored = []
        for doc_id in matches:
            score = evaluator._score(runtime, doc_id, state)
            scored.append((float(score), doc_id))
        # Negative score is impossible in this model; descending score then
        # deterministic doc id order.  Compare strings across types without
        # mixing int/str Python objects.
        scored.sort(key=lambda item: (-item[0], type(item[1]).__name__,
                                      str(item[1])))
        if top_k > 0:
            scored = scored[:top_k]

        results = []
        for score, doc_id in scored:
            result = {"doc_id": doc_id, "score": round(score, 8)}
            if with_snippet:
                text = self.index.get_text(doc_id) or ""
                result["snippet"] = make_snippet(self.index, runtime, text)
            results.append(result)
        return results

    # ------------------------------------------------------------------
    # Persistence and file workflows
    # ------------------------------------------------------------------
    def save(self, path: str) -> None:
        save_index(path, self.index, self.synonyms)

    @classmethod
    def load(cls, path: str) -> "KBSearch":
        index, synonyms = load_index(path)
        engine = cls(use_stopwords=index.analyzer.use_stopwords)
        engine.index = index
        engine.analyzer = index.analyzer
        engine.synonyms = synonyms
        return engine

    @staticmethod
    def _read_text_file(path: str) -> str:
        # utf-8-sig transparently removes a common Windows BOM without
        # affecting ordinary UTF-8 repair manuals.
        with open(path, "r", encoding="utf-8-sig") as handle:
            return handle.read()

    @staticmethod
    def _derive_title(path: str, text: str) -> str:
        for line in text.splitlines():
            stripped = line.strip()
            if stripped:
                return stripped[:120]
        return os.path.basename(path)

    def _upsert_file(self, path: str, doc_id, force: bool = False) -> bool:
        abs_path = os.path.abspath(path)
        if doc_id is None:
            doc_id = self._find_doc_by_source(abs_path)
        if doc_id is None:
            doc_id = os.path.basename(abs_path)
        existing = self.index.get_record(doc_id)
        if not os.path.exists(abs_path) and existing is not None:
            source = existing.get("source")
            if source and os.path.exists(source):
                abs_path = os.path.abspath(source)
        mtime = os.path.getmtime(abs_path)
        if existing is not None:
            if not force and existing.get("mtime") == mtime:
                return False
            # Ensure old postings disappear before adding the replacement.
            self.index.remove_document(doc_id)
        text = self._read_text_file(abs_path)
        title = self._derive_title(abs_path, text)
        self.add_document(doc_id, text, title=title, source=abs_path)
        self.index.documents[doc_id]["mtime"] = mtime
        return True

    def _find_doc_by_source(self, path: str):
        abs_path = os.path.abspath(path)
        normalized_rel = os.path.normpath(path).replace(os.sep, "/")
        normalized = os.path.normpath(path)
        suffix = os.sep + normalized if os.path.isabs(normalized) else None
        for doc_id, record in self.index.documents.items():
            source = record.get("source")
            if source == abs_path:
                return doc_id
            if suffix and source and source.endswith(suffix):
                return doc_id
            # Directory indexing uses paths relative to the scanned root as
            # ids; accept that id directly or by source basename fallback.
            if isinstance(doc_id, str) and doc_id == normalized_rel:
                return doc_id
            if (not os.path.isabs(normalized) and os.sep not in normalized
                    and source and os.path.basename(source) == normalized):
                return doc_id
        return None

    def update_file(self, path: str, doc_id=None, force: bool = True) -> bool:
        """Rebuild postings only for one changed text file.

        ``path`` may be an actual filesystem path or a relative doc id created
        by :meth:`index_directory`; in the latter case the stored source path
        is used to locate the file.
        """
        if doc_id is None:
            doc_id = self._find_doc_by_source(path)
        return self._upsert_file(path, doc_id, force=force)

    def index_directory(self, directory: str, reindex: bool = False,
                        recursive: bool = True) -> dict:
        """Scan a directory for ``.txt`` files and add/update them."""
        root = os.path.abspath(directory)
        if not os.path.isdir(root):
            raise FileNotFoundError("目录不存在: %s" % root)
        if reindex:
            for doc_id in [doc_id for doc_id, record in self.index.documents.items()
                           if str(record.get("source", "")).startswith(root + os.sep)]:
                self.remove_document(doc_id)

        files = []
        if recursive:
            for current, _, names in os.walk(root):
                for name in names:
                    if name.lower().endswith(".txt") and name.lower() != "synonyms.txt":
                        files.append(os.path.join(current, name))
        else:
            for name in os.listdir(root):
                path = os.path.join(root, name)
                if (os.path.isfile(path) and name.lower().endswith(".txt")
                        and name.lower() != "synonyms.txt"):
                    files.append(path)
        files.sort()

        added = updated = unchanged = 0
        for path in files:
            rel_doc_id = os.path.relpath(path, root).replace(os.sep, "/")
            known = self._find_doc_by_source(os.path.abspath(path))
            doc_id = known if known is not None else rel_doc_id
            changed = self._upsert_file(path, doc_id, force=reindex)
            if changed:
                if known is not None or reindex:
                    updated += 1
                else:
                    added += 1
            else:
                unchanged += 1
        return {"files": len(files), "added": added, "updated": updated,
                "unchanged": unchanged}
