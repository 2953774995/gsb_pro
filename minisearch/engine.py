"""SearchEngine：文档管理 + 查询入口。"""

from .errors import SearchError
from .index import InvertedIndex
from .query import EvalContext, parse
from .snippet import make_snippet
from .tokenizer import DEFAULT_STOPWORDS, tokenize


class SearchEngine:
    """内存全文搜索引擎。

    :param use_stopwords: 是否启用内置停止词表（默认开启）
    :param use_stemming: 是否启用简化词干化（默认开启）
    :param stopwords: 自定义停止词集合（None 使用内置表）
    """

    def __init__(self, use_stopwords=True, use_stemming=True, stopwords=None):
        self.use_stopwords = use_stopwords
        self.use_stemming = use_stemming
        self.stopwords = DEFAULT_STOPWORDS if stopwords is None else frozenset(stopwords)
        self._index = InvertedIndex()

    # ------------------------------------------------------------ 文档管理

    @staticmethod
    def _validate_doc_id(doc_id):
        if isinstance(doc_id, bool) or not isinstance(doc_id, (int, str)):
            raise TypeError("doc_id 必须是 int 或 str，得到 %r" % type(doc_id).__name__)
        if isinstance(doc_id, str) and not doc_id:
            raise ValueError("doc_id 不能为空字符串")

    def add_document(self, doc_id, text):
        """添加文档；同 doc_id 重复添加会覆盖旧文档。"""
        self._validate_doc_id(doc_id)
        if not isinstance(text, str):
            raise TypeError("text 必须是 str")
        tokens = tokenize(
            text,
            use_stopwords=self.use_stopwords,
            use_stemming=self.use_stemming,
            stopwords=self.stopwords,
        )
        self._index.add_document(doc_id, tokens, text)

    def remove_document(self, doc_id):
        """删除文档并同步清理索引。返回是否实际删除。"""
        return self._index.remove_document(doc_id)

    def document_count(self):
        """当前文档数。"""
        return self._index.num_docs

    # ------------------------------------------------------------ 查询

    def search(self, query, top_k=10, with_snippet=False):
        """执行查询，返回按分数降序的结果列表。

        每个结果为 {"doc_id": ..., "score": float}，
        with_snippet=True 时附加 "snippet" 字段。
        top_k=0 表示返回全部结果。无命中返回空列表。
        """
        if top_k < 0:
            raise SearchError("top_k 必须 >= 0（0 表示返回全部）")
        ast = parse(query)  # 空查询/非法查询在此抛 SearchError
        if self._index.num_docs == 0:
            return []
        ctx = EvalContext(
            self._index,
            use_stopwords=self.use_stopwords,
            use_stemming=self.use_stemming,
            stopwords=self.stopwords,
        )
        scores = ast.evaluate(ctx)
        if not scores:
            return []
        # 分数降序；同分按 doc_id 字符串排序保证确定性
        ranked = sorted(scores.items(), key=lambda kv: (-kv[1], str(kv[0])))
        if top_k:
            ranked = ranked[:top_k]
        matched_terms = ast.terms(ctx) if with_snippet else None
        results = []
        for doc_id, score in ranked:
            item = {"doc_id": doc_id, "score": score}
            if with_snippet:
                item["snippet"] = make_snippet(
                    self._index.documents[doc_id],
                    matched_terms,
                    use_stemming=self.use_stemming,
                )
            results.append(item)
        return results
