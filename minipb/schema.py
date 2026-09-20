"""minipb schema（.mpb 文件）的手写解析器。

语法：

    message Person {
      required string name = 1;
      optional int32 age = 2;
      repeated string emails = 3;
      optional Address addr = 4;
    }

支持 // 行注释和 /* */ 块注释。所有错误都带行号（SchemaError）。
"""

import re

from .errors import SchemaError
from .runtime import SCALAR_TYPES

MAX_FIELD_NUMBER = 2047

_TOKEN_RE = re.compile(r"""
    (?P<ident>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<number>[0-9]+)
  | (?P<symbol>[{}=;])
  | (?P<linecomment>//[^\n]*)
  | (?P<blockcomment>/\*.*?\*/)
  | (?P<ws>\s+)
  | (?P<mismatch>.)
""", re.VERBOSE | re.DOTALL)

_LABELS = ("required", "optional", "repeated")


class FieldDef(object):
    __slots__ = ("name", "type_name", "label", "number", "line")

    def __init__(self, name, type_name, label, number, line):
        self.name = name
        self.type_name = type_name
        self.label = label
        self.number = number
        self.line = line


class MessageDef(object):
    __slots__ = ("name", "fields", "line")

    def __init__(self, name, fields, line):
        self.name = name
        self.fields = fields
        self.line = line


class Schema(object):
    def __init__(self, messages):
        self.messages = messages


class _Token(object):
    __slots__ = ("kind", "value", "line")

    def __init__(self, kind, value, line):
        self.kind = kind
        self.value = value
        self.line = line

    def __repr__(self):
        return "Token(%s, %r, line=%d)" % (self.kind, self.value, self.line)


def _tokenize(text):
    tokens = []
    pos = 0
    line = 1
    for m in _TOKEN_RE.finditer(text):
        kind = m.lastgroup
        value = m.group()
        pos = m.end()
        if kind in ("ws", "linecomment", "blockcomment"):
            line += value.count("\n")
            continue
        if kind == "mismatch":
            raise SchemaError("无法识别的字符 %r" % value, line)
        tokens.append(_Token(kind, value, line))
    if pos < len(text):
        raise SchemaError("无法识别的字符 %r" % text[pos], line)
    tokens.append(_Token("eof", "<eof>", line))
    return tokens


class _Parser(object):
    def __init__(self, tokens):
        self.tokens = tokens
        self.i = 0

    def peek(self):
        return self.tokens[self.i]

    def next(self):
        tok = self.tokens[self.i]
        self.i += 1
        return tok

    def expect(self, kind, value=None):
        tok = self.peek()
        if tok.kind != kind or (value is not None and tok.value != value):
            want = value if value is not None else kind
            raise SchemaError("期望 %r，得到 %r" % (want, tok.value), tok.line)
        return self.next()

    def parse_schema(self):
        messages = []
        names = set()
        while self.peek().kind != "eof":
            msg = self.parse_message()
            if msg.name in names:
                raise SchemaError("message 名 %r 重复定义" % msg.name, msg.line)
            names.add(msg.name)
            messages.append(msg)
        if not messages:
            raise SchemaError("schema 为空：至少需要一个 message", 1)
        self._validate_types(messages, names)
        return Schema(messages)

    def parse_message(self):
        kw = self.expect("ident", "message")
        name_tok = self.expect("ident")
        self.expect("symbol", "{")
        fields = []
        seen_numbers = {}
        seen_names = set()
        while self.peek().value != "}":
            if self.peek().kind == "eof":
                prev_line = self.tokens[self.i - 1].line
                raise SchemaError(
                    "message %r 缺少结束的 '}'" % name_tok.value, prev_line)
            field = self.parse_field()
            if field.number in seen_numbers:
                raise SchemaError(
                    "字段编号 %d 重复（%r 与 %r）"
                    % (field.number, seen_numbers[field.number], field.name),
                    field.line)
            if field.name in seen_names:
                raise SchemaError("字段名 %r 重复" % field.name, field.line)
            seen_numbers[field.number] = field.name
            seen_names.add(field.name)
            fields.append(field)
        self.next()  # 消费 "}"
        return MessageDef(name_tok.value, fields, kw.line)

    def parse_field(self):
        label_tok = self.expect("ident")
        if label_tok.value not in _LABELS:
            raise SchemaError(
                "期望字段修饰 required/optional/repeated，得到 %r"
                % label_tok.value, label_tok.line)
        type_tok = self.expect("ident")
        name_tok = self.expect("ident")
        self.expect("symbol", "=")
        num_tok = self.expect("number")
        number = int(num_tok.value)
        if not (1 <= number <= MAX_FIELD_NUMBER):
            raise SchemaError(
                "字段编号 %d 超出范围 [1, %d]" % (number, MAX_FIELD_NUMBER),
                num_tok.line)
        if self.peek().value != ";":
            raise SchemaError("字段 %r 后缺少 ';'" % name_tok.value,
                              num_tok.line)
        self.next()
        return FieldDef(name_tok.value, type_tok.value, label_tok.value,
                        number, label_tok.line)

    def _validate_types(self, messages, message_names):
        for msg in messages:
            for f in msg.fields:
                if f.type_name in SCALAR_TYPES:
                    continue
                if f.type_name not in message_names:
                    raise SchemaError(
                        "未知类型 %r（不是内置类型，也不是本文件定义的 message）"
                        % f.type_name, f.line)


def parse(text):
    """解析 .mpb 文本，返回 Schema。语法错误抛 SchemaError（带行号）。"""
    return _Parser(_tokenize(text)).parse_schema()
