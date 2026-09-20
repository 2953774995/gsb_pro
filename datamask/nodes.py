"""模式 AST 节点定义。

解析器把模式文本解析为以下节点构成的显式语法树，
编译器再将其翻译为匹配虚拟机执行的指令序列。
"""


class Node(object):
    __slots__ = ()


class Empty(Node):
    """空节点（空模式、空交替分支、空分组体）。"""
    __slots__ = ()

    def __repr__(self):
        return "Empty()"


class Literal(Node):
    """单个字面量字符。"""
    __slots__ = ("ch",)

    def __init__(self, ch):
        self.ch = ch

    def __repr__(self):
        return "Literal(%r)" % self.ch


class Any(Node):
    """通配符 . （不匹配换行符）。"""
    __slots__ = ()

    def __repr__(self):
        return "Any()"


class CharClass(Node):
    """字符类 [abc] / [^abc] / [a-z0-9]。

    items 元素为二元/三元组：
        ("c", ch)        单个字符
        ("r", lo, hi)    字符范围（闭区间，按码点比较）
        ("k", code)      字符类缩写 d/D/w/W/s/S
    """
    __slots__ = ("items", "negated")

    def __init__(self, items, negated):
        self.items = items
        self.negated = negated

    def __repr__(self):
        return "CharClass(%r, negated=%r)" % (self.items, self.negated)


class Anchor(Node):
    """锚点：kind 为 'bol'（^）或 'eol'（$）。"""
    __slots__ = ("kind",)

    def __init__(self, kind):
        self.kind = kind

    def __repr__(self):
        return "Anchor(%r)" % self.kind


class Concat(Node):
    """顺序连接。"""
    __slots__ = ("children",)

    def __init__(self, children):
        self.children = children

    def __repr__(self):
        return "Concat(%r)" % (self.children,)


class Alt(Node):
    """交替 a|b|c，分支按从左到右偏好。"""
    __slots__ = ("branches",)

    def __init__(self, branches):
        self.branches = branches

    def __repr__(self):
        return "Alt(%r)" % (self.branches,)


class NonCapture(Node):
    """非捕获分组 (?: ...)：仅保留分组边界，不产生捕获。"""
    __slots__ = ("child",)

    def __init__(self, child):
        self.child = child

    def __repr__(self):
        return "NonCapture(%r)" % (self.child,)


class Group(Node):
    """捕获分组。index 从 1 开始，按左括号出现顺序编号；name 可空。"""
    __slots__ = ("index", "name", "child")

    def __init__(self, index, name, child):
        self.index = index
        self.name = name
        self.child = child

    def __repr__(self):
        return "Group(%d, name=%r, %r)" % (self.index, self.name, self.child)


class Repeat(Node):
    """量词。lo <= 重复次数 <= hi；hi 为 None 表示无上限。greedy 表示贪婪。"""
    __slots__ = ("child", "lo", "hi", "greedy")

    def __init__(self, child, lo, hi, greedy):
        self.child = child
        self.lo = lo
        self.hi = hi
        self.greedy = greedy

    def __repr__(self):
        return "Repeat(%r, {%s,%s}, greedy=%r)" % (
            self.child, self.lo, "" if self.hi is None else self.hi, self.greedy)
