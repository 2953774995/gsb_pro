"""Compile parsed query syntax into index-aware evaluable query trees."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from .errors import SearchError
from .index import InvertedIndex
from .parser import AND as P_AND, OR as P_OR, NOT as P_NOT, QueryNode
from .synonyms import SynonymStore
from .tokenizer import Analyzer


@dataclass
class RuntimeNode:
    kind: str
    children: List["RuntimeNode"] = field(default_factory=list)
    term: Optional[str] = None
    terms: Optional[Tuple[str, ...]] = None
    prefix: Optional[str] = None
    concept: Optional[str] = None
    synonym_group: bool = False


@dataclass
class _EvalState:
    docs: Dict[int, Set[object]] = field(default_factory=dict)


class QueryCompiler:
    def __init__(self, analyzer: Analyzer,
                 synonyms: Optional[SynonymStore] = None) -> None:
        self.analyzer = analyzer
        self.synonyms = synonyms

    def compile(self, node: QueryNode) -> RuntimeNode:
        if node.type == P_AND:
            return RuntimeNode("AND", [self.compile(node.children[0]),
                                       self.compile(node.children[1])])
        if node.type == P_OR:
            return RuntimeNode("OR", [self.compile(node.children[0]),
                                      self.compile(node.children[1])])
        if node.type == P_NOT:
            return RuntimeNode("NOT", [self.compile(node.children[0])])
        return self._compile_leaf(node)

    def _terms(self, value: str, allow_empty: bool = False) -> Tuple[str, ...]:
        terms = tuple(token.term for token in self.analyzer.analyze(value))
        if not terms and not allow_empty:
            raise SearchError("查询只包含空白、标点或停止词，无法检索")
        return terms

    def _make_variant(self, terms: Tuple[str, ...], concept: str) -> RuntimeNode:
        if len(terms) == 1:
            return RuntimeNode("TERM", term=terms[0], concept=concept)
        return RuntimeNode("PHRASE", terms=terms, concept=concept)

    def _compile_leaf(self, node: QueryNode) -> RuntimeNode:
        if node.leaf_kind == "PHRASE":
            all_terms = tuple(token.term for token in
                              self.analyzer.tokenize_all(node.value or ""))
            terms = tuple(term for term in all_terms
                          if not self.analyzer.is_stop_term(term))
            if not all_terms:
                raise SearchError("短语查询为空或只包含标点符号")
            # A quoted all-stop phrase is still an exact textual phrase; it
            # scores zero but can be matched through stored stop positions.
            return RuntimeNode("PHRASE", terms=all_terms,
                               concept="phrase:" + "|".join(terms))

        if node.leaf_kind == "PREFIX":
            all_terms = tuple(token.term for token in
                              self.analyzer.tokenize_all(node.value or ""))
            terms = tuple(term for term in all_terms
                          if not self.analyzer.is_stop_term(term))
            if len(all_terms) == 1:
                term = all_terms[0]
                if self.analyzer.is_stop_term(term):
                    raise SearchError("前缀查询不能只使用停止词")
                return RuntimeNode("PREFIX", prefix=term,
                                   concept="prefix:" + term)
            # English analysis yields one term.  A multi-character CJK prefix
            # such as 压缩* requires those characters to occur in one
            # contiguous CJK run; this is exactly a character phrase.
            return RuntimeNode(
                "PHRASE", terms=terms,
                concept="prefix-phrase:" + "|".join(terms))

        # A bare word is expanded through synonyms.  A contiguous CJK run is
        # naturally represented as a character-adjacency phrase.
        terms = self._terms(node.value or "")
        alternatives = [terms]
        group_id, group = (
            self.synonyms.get_group(terms) if self.synonyms else (None, None)
        )
        if group:
            alternatives = []
            seen = set()
            for variant in group:
                if variant not in seen:
                    seen.add(variant)
                    alternatives.append(variant)
        if len(alternatives) == 1:
            return self._make_variant(alternatives[0],
                                      self._concept_for(alternatives[0]))
        concept = "syn:%d" % group_id
        children = [self._make_variant(variant, concept)
                    for variant in alternatives]
        return RuntimeNode("OR", children=children, concept=concept,
                           synonym_group=True)

    @staticmethod
    def _concept_for(terms: Tuple[str, ...]) -> str:
        return terms[0] if len(terms) == 1 else "phrase:" + "|".join(terms)


def _phrase_matches(index: InvertedIndex, terms: Tuple[str, ...],
                    doc_id: object) -> bool:
    if len(terms) == 1:
        if index.analyzer.is_stop_term(terms[0]):
            return bool(index.positions_for_phrase(terms[0], doc_id))
        return index.term_frequency(terms[0], doc_id) > 0
    # Stop words are not in df/postings but still have stored positions.
    meaningful_terms = [term for term in set(terms)
                        if not index.analyzer.is_stop_term(term)]
    if not meaningful_terms:
        position_sets = {term: set(index.positions_for_phrase(term, doc_id))
                         for term in set(terms)}
        for first_position in position_sets.get(terms[0], ()):
            if all(first_position + offset in position_sets[term]
                   for offset, term in enumerate(terms)):
                return True
        return False
    if any(index.term_frequency(term, doc_id) == 0
           for term in meaningful_terms):
        return False
    # Anchor on the rarest term to minimize position checks.
    anchor = min(set(meaningful_terms),
                 key=lambda t: index.document_frequency(t))
    anchor_offsets = [offset for offset, term in enumerate(terms)
                      if term == anchor]
    position_sets = {term: set(index.positions_for_phrase(term, doc_id))
                     for term in set(terms)}
    for term in set(terms):
        if not position_sets.get(term):
            return False
    for anchor_position in index.positions(anchor, doc_id):
        for anchor_offset in anchor_offsets:
            ok = True
            for offset, term in enumerate(terms):
                if anchor_position - anchor_offset + offset not in position_sets[term]:
                    ok = False
                    break
            if ok:
                return True
    return False


class QueryEvaluator:
    def __init__(self, index: InvertedIndex) -> None:
        self.index = index

    def evaluate_docs(self, root: RuntimeNode) -> Set[object]:
        universe = set(self.index.documents)
        state = _EvalState()
        return self._docs(root, universe, state)

    def score(self, root: RuntimeNode, doc_id: object) -> float:
        state = _EvalState()
        universe = set(self.index.documents)
        self._docs(root, universe, state)
        return self._score(root, doc_id, state)

    def _docs(self, node: RuntimeNode, universe: Set[object],
              state: _EvalState) -> Set[object]:
        cached = state.docs.get(id(node))
        if cached is not None:
            return cached
        if node.kind == "TERM":
            result = set(self.index.docs_for_term(node.term))
        elif node.kind == "PREFIX":
            result = set()
            for term in self.index.terms_with_prefix(node.prefix):
                result.update(self.index.docs_for_term(term))
        elif node.kind == "PHRASE":
            candidates = set(universe)
            for term in set(node.terms):
                if self.index.analyzer.is_stop_term(term):
                    continue
                candidates &= set(self.index.docs_for_term(term))
                if not candidates:
                    break
            result = {doc_id for doc_id in candidates
                      if _phrase_matches(self.index, node.terms, doc_id)}
        elif node.kind == "AND":
            result = set.intersection(*(self._docs(child, universe, state)
                                        for child in node.children))
        elif node.kind == "OR":
            result = set()
            for child in node.children:
                result.update(self._docs(child, universe, state))
        elif node.kind == "NOT":
            result = universe - self._docs(node.children[0], universe, state)
        else:  # pragma: no cover - defensive
            raise SearchError("未知查询节点: %s" % node.kind)
        state.docs[id(node)] = result
        return result

    def _score(self, node: RuntimeNode, doc_id: object,
               state: _EvalState) -> float:
        if node.kind == "TERM":
            return self.index.term_weight(node.term, doc_id)
        if node.kind == "PREFIX":
            value = 0.0
            for term in self.index.terms_with_prefix(node.prefix):
                value = max(value, self.index.term_weight(term, doc_id))
            return value
        if node.kind == "PHRASE":
            if not _phrase_matches(self.index, node.terms, doc_id):
                return 0.0
            return sum(
                self.index.term_weight(term, doc_id)
                for term in set(node.terms)
                if not self.index.analyzer.is_stop_term(term)
            )

        if node.kind == "NOT":
            return 0.0
        if node.synonym_group:
            # One equivalence concept: score the best matching variant only.
            # This is what prevents "冰箱 OR its-synonyms" double counting.
            return max((self._score(child, doc_id, state)
                        for child in node.children), default=0.0)
        # Ordinary AND/OR score all positive children that match.  NOT
        # contributes no score.
        return sum(self._score(child, doc_id, state)
                   for child in node.children)
