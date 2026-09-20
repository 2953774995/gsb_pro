"""编译器：把 AST 翻译为匹配虚拟机的指令序列。

指令集（元组，首元素为操作码）::

    (CHAR, ch, folded)      匹配单个字符；folded 为预计算的小写形式（可空）
    (CLASS, items, negated) 匹配字符类；items 已预编译
    (ANY,)                  匹配除换行外的任意字符
    (BOL,) / (EOL,)         行首 / 行尾锚点
    (SAVE, slot)            记录当前位置到捕获槽
    (SPLIT, prefer, other)  分叉：优先 prefer，回溯时尝试 other
    (JMP, target)           无条件跳转
    (MATCH,)                匹配成功

量词 {m,n} 通过展开实现：m 份必选拷贝 + (n-m) 层嵌套可选；
{m,} 为 m 份拷贝 + 一个星号循环。展开规模受 MAX_PROGRAM 限制，
防止 (?:a{65535}){65535} 之类的模式耗尽内存。
"""

from . import nodes
from .errors import PatternError

# 操作码
CHAR = 0
CLASS = 1
ANY = 2
BOL = 3
EOL = 4
SAVE = 5
SPLIT = 6
JMP = 7
MATCH = 8

# 预编译字符类条目的类别标记
_ITEM_CHAR = 0
_ITEM_RANGE = 1
_ITEM_CODE = 2

# 展开后的指令数上限
MAX_PROGRAM = 1000000


def _casefold(ch):
    folded = ch.casefold()
    return folded if len(folded) == 1 else None


class Program(object):
    __slots__ = ("code", "n_slots", "n_groups", "group_names")

    def __init__(self, code, n_slots, n_groups, group_names):
        self.code = code
        self.n_slots = n_slots
        self.n_groups = n_groups
        self.group_names = group_names


class _Compiler(object):
    def __init__(self):
        self.code = []

    def emit(self, instr):
        if len(self.code) >= MAX_PROGRAM:
            raise PatternError(
                "pattern too large after expansion (limit %d instructions)"
                % MAX_PROGRAM)
        self.code.append(instr)
        return len(self.code) - 1

    def patch(self, index, instr):
        self.code[index] = instr

    # ------------------------------------------------------------------
    def gen(self, node):
        if isinstance(node, nodes.Empty):
            return
        if isinstance(node, nodes.Literal):
            self.emit((CHAR, node.ch, _casefold(node.ch)))
            return
        if isinstance(node, nodes.Any):
            self.emit((ANY,))
            return
        if isinstance(node, nodes.CharClass):
            self.emit((CLASS, self._compile_items(node.items), node.negated))
            return
        if isinstance(node, nodes.Anchor):
            self.emit((BOL,) if node.kind == "bol" else (EOL,))
            return
        if isinstance(node, nodes.Concat):
            for child in node.children:
                self.gen(child)
            return
        if isinstance(node, nodes.Alt):
            self._gen_alt(node.branches)
            return
        if isinstance(node, nodes.NonCapture):
            self.gen(node.child)
            return
        if isinstance(node, nodes.Group):
            self.emit((SAVE, 2 * node.index))
            self.gen(node.child)
            self.emit((SAVE, 2 * node.index + 1))
            return
        if isinstance(node, nodes.Repeat):
            self._gen_repeat(node)
            return
        raise AssertionError("unknown node: %r" % node)

    @staticmethod
    def _compile_items(items):
        compiled = []
        for item in items:
            if item[0] == "c":
                compiled.append((_ITEM_CHAR, item[1], _casefold(item[1])))
            elif item[0] == "r":
                compiled.append((_ITEM_RANGE, ord(item[1]), ord(item[2])))
            else:
                compiled.append((_ITEM_CODE, item[1]))
        return tuple(compiled)

    # ------------------------------------------------------------------
    def _gen_alt(self, branches):
        end_jumps = []
        for i, branch in enumerate(branches):
            if i < len(branches) - 1:
                split_at = self.emit((SPLIT, 0, 0))  # 稍后回填
            self.gen(branch)
            if i < len(branches) - 1:
                jmp_at = self.emit((JMP, 0))
                end_jumps.append(jmp_at)
                # 当前分支失败时跳到下一分支入口
                self.patch(split_at, (SPLIT, split_at + 1, len(self.code)))
        end = len(self.code)
        for jmp_at in end_jumps:
            self.patch(jmp_at, (JMP, end))

    # ------------------------------------------------------------------
    def _gen_repeat(self, node):
        lo, hi = node.lo, node.hi
        # m 份必选拷贝
        for _ in range(lo):
            self.gen(node.child)
        if hi is None:
            # 剩余部分等价于星号循环
            self._gen_star(node.child, node.greedy)
        else:
            # (hi - lo) 层嵌套可选
            self._gen_optional_chain(node.child, hi - lo, node.greedy)

    def _gen_star(self, child, greedy):
        loop = len(self.code)
        split_at = self.emit((SPLIT, 0, 0))
        body = len(self.code)
        self.gen(child)
        self.emit((JMP, loop))
        end = len(self.code)
        if greedy:
            self.patch(split_at, (SPLIT, body, end))
        else:
            self.patch(split_at, (SPLIT, end, body))

    def _gen_optional_chain(self, child, count, greedy):
        splits = []
        for _ in range(count):
            split_at = self.emit((SPLIT, 0, 0))
            splits.append((split_at, len(self.code)))
            self.gen(child)
        end = len(self.code)
        for split_at, body in splits:
            if greedy:
                self.patch(split_at, (SPLIT, body, end))
            else:
                self.patch(split_at, (SPLIT, end, body))


def compile_ast(parse_result):
    """把 ParseResult 编译为 Program。"""
    compiler = _Compiler()
    compiler.emit((SAVE, 0))
    compiler.gen(parse_result.ast)
    compiler.emit((SAVE, 1))
    compiler.emit((MATCH,))
    n_slots = 2 + 2 * parse_result.n_groups
    return Program(compiler.code, n_slots,
                   parse_result.n_groups, parse_result.group_names)
