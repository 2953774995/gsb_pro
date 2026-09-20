""".mpb schema 文件的解析器（手写，不依赖第三方库）。

语法:
    message Person {
      required string name = 1;
      optional int32 age = 2;
      repeated string emails = 3;
      optional Address addr = 4;
    }

支持 // 行注释。字段编号范围 1..2047，同一 message 内不能重复。
"""

import re
from dataclasses import dataclass, field as _dc_field

from .errors import SchemaError

BUILTIN_TYPES = frozenset(
    [
        "int32", "int64", "uint32", "uint64", "sint32", "sint64",
        "bool", "string", "bytes", "double",
    ]
)

LABELS = frozenset(["required", "optional", "repeated"])

MIN_FIELD_NUMBER = 1
MAX_FIELD_NUMBER = 2047

_TOKEN_RE = re.compile(
    r"""
      (?P<ws>\s+)
    | (?P<comment>//[^\n]*)
    | (?P<ident>[A-Za-z_][A-Za-z0-9_]*)
    | (?P<number>[0-9]+)
    | (?P<punct>[{}=;])
    """,
    re.VERBOSE,
)


@dataclass
class FieldDef:
    label: str
    type: str
    name: str
    number: int
    line: int


@dataclass
class MessageDef:
    name: str
    line: int
    fields: list = _dc_field(default_factory=list)


@dataclass
class Schema:
    messages: list = _dc_field(default_factory=list)


def _tokenize(text):
    """产出 (kind, value, line) 三元组。"""
    pos = 0
    line = 1
    n = len(text)
    while pos < n:
        m = _TOKEN_RE.match(text, pos)
        if m is None:
            raise SchemaError("unexpected character %r" % text[pos], line)
        kind = m.lastgroup
        value = m.group()
        if kind not in ("ws", "comment"):
            yield kind, value, line
        line += value.count("\n")
        pos = m.end()


class _Parser:
    def __init__(self, text):
        self.tokens = list(_tokenize(text))
        self.i = 0

    def peek(self):
        if self.i < len(self.tokens):
            return self.tokens[self.i]
        return None

    def next(self):
        tok = self.peek()
        if tok is None:
            raise SchemaError("unexpected end of file", self._last_line())
        self.i += 1
        return tok

    def expect(self, kind, value=None):
        tok = self.next()
        if tok[0] != kind or (value is not None and tok[1] != value):
            want = value if value is not None else kind
            raise SchemaError("expected %r, got %r" % (want, tok[1]), tok[2])
        return tok

    def _last_line(self):
        if self.tokens:
            return self.tokens[-1][2]
        return 1

    # -- 语法 ---------------------------------------------------------------

    def parse_schema(self):
        schema = Schema()
        names = {}
        while self.peek() is not None:
            msg = self.parse_message()
            if msg.name in names:
                raise SchemaError(
                    "duplicate message name %r" % msg.name, msg.line
                )
            names[msg.name] = msg
            schema.messages.append(msg)
        if not schema.messages:
            raise SchemaError("schema file defines no messages", 1)
        # 校验字段类型：内建类型或本文件定义的 message
        for msg in schema.messages:
            for f in msg.fields:
                if f.type not in BUILTIN_TYPES and f.type not in names:
                    raise SchemaError("unknown type %r" % f.type, f.line)
        return schema

    def parse_message(self):
        _, _, line = self.expect("ident", "message")
        _, name, _ = self.expect("ident")
        self.expect("punct", "{")
        msg = MessageDef(name=name, line=line)
        seen_numbers = {}
        seen_names = set()
        while True:
            tok = self.peek()
            if tok is None:
                raise SchemaError(
                    "unexpected end of file, missing '}' for message %r" % name,
                    self._last_line(),
                )
            if tok == ("punct", "}", tok[2]):
                self.next()
                return msg
            field = self.parse_field()
            if field.number in seen_numbers:
                raise SchemaError(
                    "duplicate field number %d (first used at line %d)"
                    % (field.number, seen_numbers[field.number]),
                    field.line,
                )
            if field.name in seen_names:
                raise SchemaError("duplicate field name %r" % field.name, field.line)
            if not (MIN_FIELD_NUMBER <= field.number <= MAX_FIELD_NUMBER):
                raise SchemaError(
                    "field number %d out of range [%d, %d]"
                    % (field.number, MIN_FIELD_NUMBER, MAX_FIELD_NUMBER),
                    field.line,
                )
            seen_numbers[field.number] = field.line
            seen_names.add(field.name)
            msg.fields.append(field)

    def parse_field(self):
        _, label, line = self.expect("ident")
        if label not in LABELS:
            raise SchemaError(
                "expected one of required/optional/repeated, got %r" % label, line
            )
        _, ftype, _ = self.expect("ident")
        _, fname, _ = self.expect("ident")
        self.expect("punct", "=")
        _, num, num_line = self.expect("number")
        self.expect("punct", ";")
        return FieldDef(label=label, type=ftype, name=fname, number=int(num), line=line)


def parse_schema(text):
    """解析 .mpb 文本，返回 Schema。失败抛 SchemaError（带行号）。"""
    return _Parser(text).parse_schema()
