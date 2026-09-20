"""递归下降解析器：模式文本 -> 显式 AST。

语法（EBNF 风格）::

    pattern    := alternation
    alternation:= concat ("|" concat)*
    concat     := repeat*
    repeat     := atom (quantifier "?"?)*
    atom       := "(" group_body | "[" class "]" | "." | "^" | "$"
                | escape | literal
    group_body := ")" 分支              # 捕获
                | "?:" alternation ")"  # 非捕获
                | "?P<name>" alternation ")"  # 命名捕获
    quantifier := "*" | "+" | "?" | "{m}" | "{m,}" | "{m,n}"

所有错误抛 PatternError，携带原因描述与出错列号（0 起始）。
"""

from . import nodes
from .errors import PatternError
from .escapes import SIMPLE_ESCAPES, HEX_ESCAPES, HEX_DIGITS, is_class_code

# 量词 {m,n} 中 m、n 的上限
MAX_REPEAT = 65535


class ParseResult(object):
    """解析结果：AST 根节点 + 分组元信息。"""

    __slots__ = ("ast", "n_groups", "group_names")

    def __init__(self, ast, n_groups, group_names):
        self.ast = ast
        self.n_groups = n_groups
        self.group_names = group_names  # {name: index}


class Parser(object):
    def __init__(self, pattern):
        if not isinstance(pattern, str):
            raise TypeError("pattern must be str, not %s" % type(pattern).__name__)
        self.pattern = pattern
        self.pos = 0
        self.n_groups = 0
        self.group_names = {}

    # ------------------------------------------------------------------
    # 基础扫描工具
    # ------------------------------------------------------------------
    def error(self, message, pos=None):
        raise PatternError(message, self.pos if pos is None else pos, self.pattern)

    def _peek(self, offset=0):
        i = self.pos + offset
        return self.pattern[i] if i < len(self.pattern) else ""

    def _at_end(self):
        return self.pos >= len(self.pattern)

    # ------------------------------------------------------------------
    # 入口
    # ------------------------------------------------------------------
    def parse(self):
        ast = self._parse_alternation()
        if not self._at_end():
            # 顶层遇到未配对的 ')'
            self.error("unbalanced parenthesis", self.pos)
        return ParseResult(ast, self.n_groups, dict(self.group_names))

    # ------------------------------------------------------------------
    # 交替与连接
    # ------------------------------------------------------------------
    def _parse_alternation(self):
        branches = [self._parse_concat()]
        while self._peek() == "|":
            self.pos += 1
            branches.append(self._parse_concat())
        if len(branches) == 1:
            return branches[0]
        return nodes.Alt(branches)

    def _parse_concat(self):
        items = []
        while not self._at_end() and self._peek() not in "|)":
            items.append(self._parse_repeat())
        if not items:
            return nodes.Empty()
        if len(items) == 1:
            return items[0]
        return nodes.Concat(items)

    # ------------------------------------------------------------------
    # 量词
    # ------------------------------------------------------------------
    def _parse_repeat(self):
        atom = self._parse_atom()
        node = atom
        while True:
            quant = self._try_parse_quantifier()
            if quant is None:
                return node
            lo, hi, qpos = quant
            if isinstance(node, nodes.Anchor):
                self.error("nothing to repeat (anchor is not repeatable)", qpos)
            if isinstance(node, nodes.Repeat):
                self.error("multiple repeat", qpos)
            greedy = True
            if self._peek() == "?":
                self.pos += 1
                greedy = False
            node = nodes.Repeat(node, lo, hi, greedy)

    def _try_parse_quantifier(self):
        """解析一个量词，返回 (lo, hi, pos)；当前位置不是量词时返回 None。"""
        c = self._peek()
        pos = self.pos
        if c == "*":
            self.pos += 1
            return (0, None, pos)
        if c == "+":
            self.pos += 1
            return (1, None, pos)
        if c == "?":
            self.pos += 1
            return (0, 1, pos)
        if c == "{":
            return self._try_parse_brace_quantifier(pos)
        return None

    def _try_parse_brace_quantifier(self, pos):
        save = self.pos
        self.pos += 1  # 消费 '{'
        m = self._read_digits()
        if m is None:
            self.pos = save
            return None
        if self._peek() == "}":
            self.pos += 1
            lo = hi = int(m)
        elif self._peek() == ",":
            self.pos += 1
            n = self._read_digits()
            if self._peek() != "}":
                self.pos = save
                return None
            self.pos += 1
            lo = int(m)
            hi = int(n) if n is not None else None
        else:
            self.pos = save
            return None
        if lo > MAX_REPEAT or (hi is not None and hi > MAX_REPEAT):
            self.error(
                "repeat count out of range (max %d)" % MAX_REPEAT, save)
        if hi is not None and lo > hi:
            self.error(
                "min repeat (%d) greater than max repeat (%d)" % (lo, hi), save)
        return (lo, hi, save)

    def _read_digits(self):
        start = self.pos
        while self._peek().isdigit():
            self.pos += 1
        if self.pos == start:
            return None
        return self.pattern[start:self.pos]

    def _looks_like_quantifier(self):
        """从当前 '{' 位置前瞻，判断是否构成合法量词（用于报错分流）。"""
        i = self.pos + 1
        n = len(self.pattern)
        start = i
        while i < n and self.pattern[i].isdigit():
            i += 1
        if i == start:
            return False
        if i < n and self.pattern[i] == "}":
            return True
        if i < n and self.pattern[i] == ",":
            i += 1
            while i < n and self.pattern[i].isdigit():
                i += 1
            return i < n and self.pattern[i] == "}"
        return False

    # ------------------------------------------------------------------
    # 原子
    # ------------------------------------------------------------------
    def _parse_atom(self):
        c = self._peek()
        pos = self.pos
        if c == "(":
            return self._parse_group()
        if c == "[":
            return self._parse_char_class()
        if c == ".":
            self.pos += 1
            return nodes.Any()
        if c == "^":
            self.pos += 1
            return nodes.Anchor("bol")
        if c == "$":
            self.pos += 1
            return nodes.Anchor("eol")
        if c == "\\":
            return self._parse_escape_atom()
        if c in "*+?":
            self.error("nothing to repeat", pos)
        if c == "{":
            if self._looks_like_quantifier():
                self.error("nothing to repeat", pos)
            self.pos += 1
            return nodes.Literal("{")
        self.pos += 1
        return nodes.Literal(c)

    # ------------------------------------------------------------------
    # 分组
    # ------------------------------------------------------------------
    def _parse_group(self):
        start = self.pos
        self.pos += 1  # 消费 '('
        capture = True
        name = None
        if self._peek() == "?":
            self.pos += 1
            nxt = self._peek()
            if nxt == ":":
                self.pos += 1
                capture = False
            elif nxt == "P":
                self.pos += 1
                if self._peek() != "<":
                    self.error("unknown group extension '(?P'", start)
                self.pos += 1
                name = self._read_group_name(start)
                if self._peek() != ">":
                    self.error("unterminated group name", start)
                self.pos += 1
                if name in self.group_names:
                    self.error("duplicate group name %r" % name, start)
            else:
                self.error("unknown group extension '(?%s'" % nxt, start)
        index = None
        if capture:
            self.n_groups += 1
            index = self.n_groups
            if name is not None:
                self.group_names[name] = index
        child = self._parse_alternation()
        if self._peek() != ")":
            self.error("unterminated group (missing ')')", start)
        self.pos += 1
        if capture:
            return nodes.Group(index, name, child)
        return nodes.NonCapture(child)

    def _read_group_name(self, group_start):
        start = self.pos
        ch = self._peek()
        if not (ch.isalpha() or ch == "_"):
            self.error("bad character in group name", group_start)
        while self._peek().isalnum() or self._peek() == "_":
            self.pos += 1
        return self.pattern[start:self.pos]

    # ------------------------------------------------------------------
    # 字符类
    # ------------------------------------------------------------------
    def _parse_char_class(self):
        start = self.pos
        self.pos += 1  # 消费 '['
        negated = False
        if self._peek() == "^":
            negated = True
            self.pos += 1
        items = []
        first = True
        while True:
            if self._at_end():
                self.error("unterminated character class", start)
            if self._peek() == "]" and not first:
                self.pos += 1
                break
            first = False
            lo = self._parse_class_item(start)
            # 范围：a-z（'-' 后不能紧跟 ']' 或结束，否则 '-' 是字面量）
            if (lo[0] == "c" and self._peek() == "-"
                    and self._peek(1) not in ("", "]")):
                self.pos += 1  # 消费 '-'
                hi_pos = self.pos
                hi = self._parse_class_item(start)
                if hi[0] != "c":
                    self.error(
                        "bad character range (class code not allowed in range)",
                        hi_pos)
                if ord(lo[1]) > ord(hi[1]):
                    self.error(
                        "bad character range %r-%r (out of order)"
                        % (lo[1], hi[1]), hi_pos)
                items.append(("r", lo[1], hi[1]))
            else:
                items.append(lo)
        if not items:
            self.error("empty character class", start)
        return nodes.CharClass(items, negated)

    def _parse_class_item(self, class_start):
        """解析字符类内的一个元素，返回 ('c', ch) 或 ('k', code)。"""
        if self._peek() == "\\":
            esc_pos = self.pos
            self.pos += 1
            kind, value = self._parse_escape_value(esc_pos)
            if kind == "k":
                return ("k", value)
            return ("c", value)
        ch = self._peek()
        self.pos += 1
        return ("c", ch)

    # ------------------------------------------------------------------
    # 转义
    # ------------------------------------------------------------------
    def _parse_escape_atom(self):
        """分组外转义：返回 AST 节点（字面量或字符类缩写）。"""
        esc_pos = self.pos
        self.pos += 1  # 消费 '\'
        kind, value = self._parse_escape_value(esc_pos)
        if kind == "k":
            return nodes.CharClass([("k", value)], False)
        return nodes.Literal(value)

    def _parse_escape_value(self, esc_pos):
        """解析反斜杠后的转义体，返回 ('c', ch) 或 ('k', code)。"""
        if self._at_end():
            self.error("trailing backslash", esc_pos)
        c = self._peek()
        self.pos += 1
        if is_class_code(c):
            return ("k", c)
        if c in SIMPLE_ESCAPES:
            return ("c", SIMPLE_ESCAPES[c])
        if c in HEX_ESCAPES:
            return ("c", self._read_hex_escape(HEX_ESCAPES[c], esc_pos))
        if c.isdigit():
            if c == "0":
                self.error(r"unknown escape '\0'", esc_pos)
            self.error(
                r"backreference '\%s' is not supported" % c, esc_pos)
        if c.isalpha():
            self.error(r"unknown escape '\%s'" % c, esc_pos)
        # 非字母数字字符：转义后表示其字面量自身（\\ \. \* \[ 等）
        return ("c", c)

    def _read_hex_escape(self, n_digits, esc_pos):
        digits = ""
        for _ in range(n_digits):
            ch = self._peek()
            if ch not in HEX_DIGITS:
                self.error(
                    "invalid hex escape (expected %d hex digits)" % n_digits,
                    esc_pos)
            digits += ch
            self.pos += 1
        return chr(int(digits, 16))


def parse(pattern):
    """解析模式文本，返回 ParseResult。"""
    return Parser(pattern).parse()
