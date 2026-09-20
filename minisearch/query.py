"""查询语言：词法分析、语法解析（AST）与求值。

语法（AND/OR/NOT 大小写不敏感，相邻词项隐含 AND）：

    expr     := or_expr
    or_expr  := and_expr (OR and_expr)*
    and_expr := not_expr ((AND)? not_expr)*
    not_expr := NOT not_expr | primary
    primary  := '(' expr ')' | PHRASE | PREFIX | TERM
    PHRASE   := "exact phrase"     按位置列表验证相邻出现
    PREFIX   := term*              遍历词典匹配前缀

求值结果为 {doc_id: score}，打分规则见 scoring 说明（TF-IDF）。
"""

import math

from .errors import SearchError
from .tokenizer import tokenize


# ---------------------------------------------------------------- 词法分析

def _lex(query):
    """把查询字符串切分为 (kind, value) token 序列。"""
    tokens = []
    i, n = 0, len(query)
    while i < n:
        ch = query[i]
        if ch.isspace():
            i += 1
        elif ch == "(":
            tokens.append(("LPAREN", ch))
            i += 1
        elif ch == ")":
            tokens.append(("RPAREN", ch))
            i += 1
        elif ch == '"':
            j = query.find('"', i + 1)
            if j == -1:
                raise SearchError("短语查询缺少结束引号（unterminated phrase）")
            tokens.append(("PHRASE", query[i + 1 : j]))
            i = j + 1
        else:
            j = i
            while j < n and not query[j].isspace() and query[j] not in '()"':
                j += 1
            word = query[i:j]
            upper = word.upper()
            if upper in ("AND", "OR", "NOT"):
                tokens.append((upper, word))
            elif "*" in word:
                if word == "*" or not word.endswith("*") or "*" in word[:-1]:
                    raise SearchError(
                        "非法通配符用法 %r：仅支持后缀前缀查询 term*" % word
                    )
                tokens.append(("PREFIX", word[:-1]))
            else:
                tokens.append(("TERM", word))
            i = j
    return tokens


# ---------------------------------------------------------------- 语法树节点

class EvalContext:
    """求值上下文：索引 + 分词配置。"""

    def __init__(self, index, use_stopwords=True, use_stemming=True, stopwords=None):
        self.index = index
        self.use_stopwords = use_stopwords
        self.use_stemming = use_stemming
        self.stopwords = stopwords
        self.n = index.num_docs

    def normalize(self, raw):
        """把查询词原始字符串分词为 term 列表（与索引侧规范化一致）。"""
        return [
            term
            for term, _ in tokenize(
                raw,
                use_stopwords=self.use_stopwords,
                use_stemming=self.use_stemming,
                stopwords=self.stopwords,
            )
        ]

    def idf(self, term):
        """平滑 idf：log(1 + N/df)。"""
        df = self.index.df(term)
        if df == 0 or self.n == 0:
            return 0.0
        return math.log(1 + self.n / df)

    def tfidf_scores(self, term):
        """term 在所有命中文档上的 TF-IDF 分数：tf 对数归一化 (1+log10(tf)) * idf。"""
        idf = self.idf(term)
        if idf == 0.0:
            return {}
        return {
            doc_id: (1 + math.log10(posting["tf"])) * idf
            for doc_id, posting in self.index.postings.get(term, {}).items()
        }


class TermNode:
    """词项查询。多 token 查询词（如中文词）按隐含 AND 组合。"""

    def __init__(self, raw):
        self.raw = raw

    def evaluate(self, ctx):
        terms = ctx.normalize(self.raw)
        if not terms:
            # 查询词全部为停止词：视为匹配全部文档、得分 0（在 AND 中呈中性）
            return {doc_id: 0.0 for doc_id in ctx.index.documents}
        result = None
        for term in terms:
            scores = ctx.tfidf_scores(term)
            if result is None:
                result = scores
            else:
                common = result.keys() & scores.keys()
                result = {d: result[d] + scores[d] for d in common}
        return result or {}

    def terms(self, ctx):
        return set(ctx.normalize(self.raw))


class PrefixNode:
    """前缀查询 term*：遍历词典匹配前缀，命中项分数求和。"""

    def __init__(self, prefix):
        self.prefix = prefix.lower()

    def _matched_terms(self, ctx):
        return [t for t in ctx.index.lexicon() if t.startswith(self.prefix)]

    def evaluate(self, ctx):
        result = {}
        for term in self._matched_terms(ctx):
            for doc_id, score in ctx.tfidf_scores(term).items():
                result[doc_id] = result.get(doc_id, 0.0) + score
        return result

    def terms(self, ctx):
        return set(self._matched_terms(ctx))


class PhraseNode:
    """短语查询：要求各 term 在文档中按位置相邻出现。"""

    def __init__(self, raw):
        self.raw = raw

    def evaluate(self, ctx):
        terms = ctx.normalize(self.raw)
        if not terms:
            return {}
        if len(terms) == 1:
            return ctx.tfidf_scores(terms[0])
        postings_list = []
        for term in terms:
            postings = ctx.index.postings.get(term)
            if not postings:
                return {}
            postings_list.append(postings)
        candidates = set(postings_list[0])
        for postings in postings_list[1:]:
            candidates &= postings.keys()
        idf_sum = sum(ctx.idf(t) for t in terms)
        scores = {}
        for doc_id in candidates:
            first_positions = postings_list[0][doc_id]["positions"]
            rest_sets = [set(p[doc_id]["positions"]) for p in postings_list[1:]]
            count = sum(
                1
                for pos in first_positions
                if all(pos + offset + 1 in pos_set
                       for offset, pos_set in enumerate(rest_sets))
            )
            if count:
                scores[doc_id] = idf_sum * (1 + math.log10(count))
        return scores

    def terms(self, ctx):
        return set(ctx.normalize(self.raw))


class AndNode:
    def __init__(self, left, right):
        self.left, self.right = left, right

    def evaluate(self, ctx):
        left = self.left.evaluate(ctx)
        right = self.right.evaluate(ctx)
        common = left.keys() & right.keys()
        return {d: left[d] + right[d] for d in common}

    def terms(self, ctx):
        return self.left.terms(ctx) | self.right.terms(ctx)


class OrNode:
    def __init__(self, left, right):
        self.left, self.right = left, right

    def evaluate(self, ctx):
        result = dict(self.left.evaluate(ctx))
        for doc_id, score in self.right.evaluate(ctx).items():
            result[doc_id] = result.get(doc_id, 0.0) + score
        return result

    def terms(self, ctx):
        return self.left.terms(ctx) | self.right.terms(ctx)


class NotNode:
    """一元 NOT：作用于子表达式，返回补集（得分 0）。"""

    def __init__(self, child):
        self.child = child

    def evaluate(self, ctx):
        excluded = self.child.evaluate(ctx)
        return {
            doc_id: 0.0
            for doc_id in ctx.index.documents
            if doc_id not in excluded
        }

    def terms(self, ctx):
        return set()  # 被排除的词不参与摘要高亮


# ---------------------------------------------------------------- 语法分析

_OPERAND_STARTERS = ("TERM", "PHRASE", "PREFIX", "LPAREN", "NOT")


class _Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def peek(self):
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return (None, None)

    def advance(self):
        token = self.peek()
        self.pos += 1
        return token

    def parse_or(self):
        node = self.parse_and()
        while self.peek()[0] == "OR":
            self.advance()
            node = OrNode(node, self.parse_and())
        return node

    def parse_and(self):
        node = self.parse_not()
        while True:
            kind, _ = self.peek()
            if kind == "AND":
                self.advance()
                node = AndNode(node, self.parse_not())
            elif kind in _OPERAND_STARTERS:
                # 相邻词项隐含 AND
                node = AndNode(node, self.parse_not())
            else:
                return node

    def parse_not(self):
        if self.peek()[0] == "NOT":
            self.advance()
            return NotNode(self.parse_not())
        return self.parse_primary()

    def parse_primary(self):
        kind, value = self.peek()
        if kind == "LPAREN":
            self.advance()
            node = self.parse_or()
            if self.peek()[0] != "RPAREN":
                raise SearchError("括号不匹配：缺少右括号 )")
            self.advance()
            return node
        if kind == "TERM":
            self.advance()
            return TermNode(value)
        if kind == "PHRASE":
            self.advance()
            if not value.strip():
                raise SearchError("空短语查询 \"\"")
            return PhraseNode(value)
        if kind == "PREFIX":
            self.advance()
            return PrefixNode(value)
        if kind == "RPAREN":
            raise SearchError("括号不匹配：多余的右括号 )")
        if kind in ("AND", "OR"):
            raise SearchError("非法查询：运算符 %s 缺少左操作数" % value)
        if kind == "NOT":
            raise SearchError("非法查询：NOT 后缺少子表达式")
        raise SearchError("非法查询：期望词项、短语或 (，但查询已结束")


def parse(query):
    """解析查询字符串，返回 AST 根节点。非法查询抛 SearchError。"""
    if not isinstance(query, str) or not query.strip():
        raise SearchError("空查询")
    tokens = _lex(query)
    if not tokens:
        raise SearchError("空查询")
    parser = _Parser(tokens)
    node = parser.parse_or()
    if parser.pos != len(tokens):
        kind, value = tokens[parser.pos]
        if kind == "RPAREN":
            raise SearchError("括号不匹配：多余的右括号 )")
        raise SearchError("非法查询：无法解析的 token %r" % value)
    return node
