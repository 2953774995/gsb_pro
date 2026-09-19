"""模板源码分词：把源码切成 TEXT / VAR({{ }}) / TAG({% %}) token。

注释 {# ... #} 在分词阶段直接丢弃；未闭合的标记抛 TplError。
"""

from .errors import TplError

TEXT = "text"
VAR = "var"
TAG = "tag"

_OPENERS = {"{{": "}}", "{%": "%}", "{#": "#}"}


class Token(object):
    __slots__ = ("type", "content", "lineno")

    def __init__(self, type_, content, lineno):
        self.type = type_
        self.content = content
        self.lineno = lineno

    def __repr__(self):
        return "Token(%r, %r, line=%d)" % (self.type, self.content, self.lineno)


def tokenize(source):
    """把模板源码切分为 token 列表。"""
    tokens = []
    pos = 0
    lineno = 1
    n = len(source)
    while pos < n:
        # 找最近的下一个起始标记
        start = n
        opener = None
        for op in _OPENERS:
            i = source.find(op, pos)
            if i != -1 and i < start:
                start = i
                opener = op
        if opener is None:
            text = source[pos:]
            if text:
                tokens.append(Token(TEXT, text, lineno))
            break
        if start > pos:
            text = source[pos:start]
            tokens.append(Token(TEXT, text, lineno))
            lineno += text.count("\n")
        closer = _OPENERS[opener]
        tok_lineno = lineno
        end = source.find(closer, start + 2)
        if end == -1:
            raise TplError(
                "unclosed tag %r at line %d" % (opener, tok_lineno))
        content = source[start + 2:end]
        lineno += source[start:end + 2].count("\n")
        if opener == "{#":
            pass  # 注释直接丢弃
        elif opener == "{{":
            tokens.append(Token(VAR, content.strip(), tok_lineno))
        else:
            tokens.append(Token(TAG, content.strip(), tok_lineno))
        pos = end + 2
    return tokens
