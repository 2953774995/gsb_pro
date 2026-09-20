"""编译选项、Pattern 与 Match：对外的核心 API。"""

from . import vm
from .compiler import compile_ast
from .errors import PatternError  # noqa: F401  (re-export)
from .parser import parse

# 编译选项
IGNORECASE = 1 << 0   # 忽略大小写
MULTILINE = 1 << 1    # 多行模式：^/$ 匹配行首/行尾

# 便捷别名（与常见库风格一致）
I = IGNORECASE
M = MULTILINE

# 单次匹配的默认步数上限（PRD 规定 1 亿步）
DEFAULT_MAX_STEPS = 100000000


def compile(pattern, flags=0, max_steps=DEFAULT_MAX_STEPS):
    """编译模式，返回 Pattern 对象。

    flags:     IGNORECASE / MULTILINE 的按位或。
    max_steps: 单次匹配的步数预算，超限抛 PatternTimeoutError。
    """
    return Pattern(pattern, flags, max_steps)


class Pattern(object):
    """已编译的模式。提供 search/match/fullmatch/findall/finditer。"""

    def __init__(self, pattern, flags=0, max_steps=DEFAULT_MAX_STEPS):
        self.pattern = pattern
        self.flags = flags
        self.max_steps = max_steps
        result = parse(pattern)
        self._program = compile_ast(result)
        self.groups = result.n_groups
        self.groupindex = dict(result.group_names)

    # ------------------------------------------------------------------
    def _run(self, string, pos, endpos, scanning, require_end, max_steps):
        if not isinstance(string, str):
            raise TypeError("expected string for matching, not %s"
                            % type(string).__name__)
        if endpos is None:
            endpos = len(string)
        pos = max(0, pos)
        endpos = min(endpos, len(string))
        if pos > endpos:
            return None
        budget = self.max_steps if max_steps is None else max_steps
        result = vm.run(
            self._program.code, self._program.n_slots, string, pos, endpos,
            scanning=scanning, require_end=require_end,
            icase=bool(self.flags & IGNORECASE),
            multiline=bool(self.flags & MULTILINE),
            max_steps=budget)
        if result is None:
            return None
        slots, _end = result
        return Match(self, string, pos, endpos, slots)

    # ------------------------------------------------------------------
    def search(self, string, pos=0, endpos=None, max_steps=None):
        """扫描字符串，返回第一个命中的 Match，未命中返回 None。"""
        return self._run(string, pos, endpos, True, False, max_steps)

    def match(self, string, pos=0, endpos=None, max_steps=None):
        """从 pos 处开始匹配（不要求匹配到串尾）。"""
        return self._run(string, pos, endpos, False, False, max_steps)

    def fullmatch(self, string, pos=0, endpos=None, max_steps=None):
        """要求模式恰好匹配 pos..endpos 的完整区间。"""
        return self._run(string, pos, endpos, False, True, max_steps)

    def finditer(self, string, pos=0, endpos=None, max_steps=None):
        """惰性生成所有不重叠命中的 Match 迭代器。"""
        if endpos is None:
            endpos = len(string)
        p = pos
        while p <= endpos:
            m = self.search(string, p, endpos, max_steps=max_steps)
            if m is None:
                return
            yield m
            # 空命中后前进一个字符，避免死循环
            p = m.end() + 1 if m.end() == m.start() else m.end()

    def findall(self, string, pos=0, endpos=None, max_steps=None):
        """返回所有不重叠命中。

        无捕获组时返回命中串列表；恰一个捕获组时返回该组列表；
        多个捕获组时返回分组元组列表。
        """
        out = []
        for m in self.finditer(string, pos, endpos, max_steps=max_steps):
            if self.groups == 0:
                out.append(m.group(0))
            elif self.groups == 1:
                out.append(m.group(1))
            else:
                out.append(m.groups())
        return out

    def __repr__(self):
        return "datamask.compile(%r, flags=%d)" % (self.pattern, self.flags)


class Match(object):
    """一次命中的结果对象。"""

    __slots__ = ("re", "string", "pos", "endpos", "_slots")

    def __init__(self, pattern, string, pos, endpos, slots):
        self.re = pattern
        self.string = string
        self.pos = pos
        self.endpos = endpos
        self._slots = slots

    # ------------------------------------------------------------------
    def _group_index(self, ref):
        if isinstance(ref, str):
            try:
                return self.re.groupindex[ref]
            except KeyError:
                raise IndexError("unknown group name %r" % ref)
        index = int(ref)
        if not 0 <= index <= self.re.groups:
            raise IndexError("no such group: %r" % (ref,))
        return index

    def _span_of(self, index):
        start = self._slots[2 * index]
        end = self._slots[2 * index + 1]
        return start, end

    # ------------------------------------------------------------------
    def group(self, *refs):
        """group() 返回整体命中；group(n)/group(name) 返回对应捕获组。"""
        if not refs:
            refs = (0,)
        if len(refs) == 1:
            start, end = self._span_of(self._group_index(refs[0]))
            if start < 0:
                return None
            return self.string[start:end]
        return tuple(self.group(ref) for ref in refs)

    def groups(self, default=None):
        """返回全部捕获组（1..N）组成的元组，未参与的组为 default。"""
        out = []
        for i in range(1, self.re.groups + 1):
            start, end = self._span_of(i)
            out.append(self.string[start:end] if start >= 0 else default)
        return tuple(out)

    def groupdict(self, default=None):
        """返回 {组名: 内容} 字典。"""
        out = {}
        for name, index in self.re.groupindex.items():
            start, end = self._span_of(index)
            out[name] = self.string[start:end] if start >= 0 else default
        return out

    def span(self, ref=0):
        """返回 (start, end)；组未参与匹配时返回 (-1, -1)。"""
        return self._span_of(self._group_index(ref))

    def start(self, ref=0):
        return self.span(ref)[0]

    def end(self, ref=0):
        return self.span(ref)[1]

    def __repr__(self):
        return "<datamask.Match span=%r match=%r>" % (self.span(), self.group(0))
