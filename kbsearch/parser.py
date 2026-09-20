"""Tokenizer and recursive-descent parser for the kbsearch query language."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .errors import SearchError
from .tokenizer import is_cjk_char

AND = "AND"
OR = "OR"
NOT = "NOT"


@dataclass
class QueryNode:
    """Generic syntax tree before translation to index query nodes."""
    type: str
    children: List["QueryNode"] = field(default_factory=list)
    leaf_kind: Optional[str] = None
    value: Optional[str] = None


@dataclass
class SyntaxToken:
    kind: str
    value: str


class QueryLexer:
    def tokenize(self, query: str) -> List[SyntaxToken]:
        tokens = []
        i = 0
        length = len(query)
        while i < length:
            ch = query[i]
            if ch.isspace():
                i += 1
                continue
            if ch == "(":
                tokens.append(SyntaxToken("LPAREN", ch))
                i += 1
                continue
            if ch == ")":
                tokens.append(SyntaxToken("RPAREN", ch))
                i += 1
                continue
            if ch == '"':
                phrase, i = self._read_phrase(query, i + 1)
                tokens.append(SyntaxToken("PHRASE", phrase))
                continue
            if self._is_punctuation(ch):
                # Treat ordinary textual punctuation as whitespace.  This makes
                # mixed Chinese queries such as "冰箱，压缩机" equivalent to an
                # implicit AND without allowing isolated Boolean operators.
                i += 1
                continue

            if self._is_word_char(ch):
                start = i
                i += 1
                while i < length and self._is_word_char(query[i]):
                    i += 1
                word = query[start:i]
                upper = word.upper()
                if upper in (AND, OR, NOT):
                    tokens.append(SyntaxToken(upper, upper))
                else:
                    kind = "WORD"
                    if i < length and query[i] == "*":
                        i += 1
                        kind = "PREFIX"
                        if i < length and self._is_word_char(query[i]):
                            raise SearchError("前缀符号 * 只能位于词尾")
                    tokens.append(SyntaxToken(kind, word))
                continue
            raise SearchError("无法识别的查询字符: %r" % ch)
        return tokens

    @staticmethod
    def _is_word_char(ch: str) -> bool:
        return ch.isascii() and ch.isalnum() or is_cjk_char(ch)

    @staticmethod
    def _is_punctuation(ch: str) -> bool:
        category = ch in "!?.,;:，。！？；：、・．"
        symbols = ch in r"/\|-_+=#@$%&~`^<>"
        quote_like = ch in "“”‘’「」『』（）【】《》〈〉"
        dashes = ord(ch) in (0x2010, 0x2011, 0x2012, 0x2013, 0x2014,
                             0x2015, 0x2018, 0x2019)
        return category or symbols or quote_like or dashes or ch.isspace()

    @staticmethod
    def _read_phrase(query: str, start: int):
        result = []
        i = start
        escaped = False
        while i < len(query):
            ch = query[i]
            if escaped:
                result.append(ch)
                escaped = False
                i += 1
                continue
            if ch == "\\":
                escaped = True
                i += 1
                continue
            if ch == '"':
                return "".join(result), i + 1
            result.append(ch)
            i += 1
        raise SearchError("短语查询缺少结束双引号")


class QueryParser:
    """Parses with precedence NOT > AND > OR.

    Adjacent operands are treated as an implicit AND, which gives natural
    behavior to the space-separated words in ``异响 压缩机``.
    """

    def __init__(self, query: str):
        self.query = query
        self.tokens = QueryLexer().tokenize(query)
        self.pos = 0

    def parse(self) -> QueryNode:
        if not self.query.strip() or not self.tokens:
            raise SearchError("查询不能为空")
        node = self._parse_or()
        if self.pos != len(self.tokens):
            token = self.tokens[self.pos]
            raise SearchError("查询语法不完整，多余的标记: %s" % token.value)
        return node

    def _peek(self) -> Optional[SyntaxToken]:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def _consume(self) -> SyntaxToken:
        token = self._peek()
        if token is None:
            raise SearchError("查询意外结束")
        self.pos += 1
        return token

    def _parse_or(self) -> QueryNode:
        left = self._parse_and()
        while self._peek() is not None and self._peek().kind == OR:
            self._consume()
            right = self._parse_and()
            left = QueryNode(OR, [left, right])
        return left

    def _parse_and(self) -> QueryNode:
        left = self._parse_not()
        while True:
            token = self._peek()
            if token is None or token.kind in (OR, "RPAREN"):
                break
            if token.kind == AND:
                self._consume()
            elif token.kind in ("WORD", "PHRASE", "PREFIX", "LPAREN", NOT):
                # Implicit conjunction.
                pass
            else:
                raise SearchError("孤立或位置错误的 AND/OR 操作符")
            right = self._parse_not()
            left = QueryNode(AND, [left, right])
        return left

    def _parse_not(self) -> QueryNode:
        token = self._peek()
        if token is not None and token.kind == NOT:
            self._consume()
            if self._peek() is None or self._peek().kind in (AND, OR, "RPAREN"):
                raise SearchError("NOT 后缺少查询表达式")
            return QueryNode(NOT, [self._parse_not()])
        return self._parse_leaf()

    def _parse_leaf(self) -> QueryNode:
        token = self._consume()
        if token.kind == "LPAREN":
            if self._peek() is not None and self._peek().kind == "RPAREN":
                raise SearchError("括号内查询表达式为空")
            node = self._parse_or()
            closing = self._consume()
            if closing.kind != "RPAREN":
                raise SearchError("括号分组缺少右括号")
            return node
        if token.kind in ("WORD", "PHRASE", "PREFIX"):
            return QueryNode("LEAF", leaf_kind=token.kind, value=token.value)
        if token.kind in (AND, OR):
            raise SearchError("孤立或位置错误的 AND/OR 操作符")
        if token.kind == "RPAREN":
            raise SearchError("存在多余的右括号")
        raise SearchError("不支持的查询标记: %s" % token.value)


def parse_query(query: str) -> QueryNode:
    if query is None:
        raise SearchError("查询不能为空")
    return QueryParser(query).parse()
