"""倒排索引模块。

数据结构：
- postings: term -> {doc_id: {"tf": int, "positions": [int, ...]}}
- doc_lengths: doc_id -> 有效词数（去除停止词后的 term 总数）
- doc_terms: doc_id -> set(term)，用于删除文档时精确清理 postings
- documents: doc_id -> 原始文本（供摘要生成）

df(term) = len(postings[term])，O(1) 获取。
"""


class InvertedIndex:
    """内存倒排索引，支持增删文档。"""

    def __init__(self):
        self.postings = {}
        self.doc_lengths = {}
        self.doc_terms = {}
        self.documents = {}

    @property
    def num_docs(self):
        return len(self.documents)

    def add_document(self, doc_id, tokens, text):
        """添加文档。tokens 为 (term, position) 列表；同 doc_id 重复添加会先清理旧数据。"""
        if doc_id in self.documents:
            self.remove_document(doc_id)
        term_positions = {}
        for term, pos in tokens:
            term_positions.setdefault(term, []).append(pos)
        for term, positions in term_positions.items():
            self.postings.setdefault(term, {})[doc_id] = {
                "tf": len(positions),
                "positions": positions,
            }
        self.doc_terms[doc_id] = set(term_positions)
        self.doc_lengths[doc_id] = len(tokens)
        self.documents[doc_id] = text

    def remove_document(self, doc_id):
        """删除文档并清理其全部 postings，不残留任何中间态。返回是否实际删除。"""
        if doc_id not in self.documents:
            return False
        for term in self.doc_terms[doc_id]:
            term_postings = self.postings[term]
            del term_postings[doc_id]
            if not term_postings:
                del self.postings[term]
        del self.doc_terms[doc_id]
        del self.doc_lengths[doc_id]
        del self.documents[doc_id]
        return True

    def df(self, term):
        """term 的文档频率。"""
        term_postings = self.postings.get(term)
        return len(term_postings) if term_postings else 0

    def lexicon(self):
        """词典（全部已索引 term）。"""
        return self.postings.keys()
