"""渲染上下文：作用域链、未定义变量策略、loop 辅助对象。"""

from .errors import TplError


class Undefined(object):
    """非严格模式下缺失变量的占位值。

    渲染为空字符串、布尔值为 False、可迭代为空；
    继续取属性仍得到 Undefined。
    """

    __slots__ = ("_name",)

    def __init__(self, name):
        self._name = name

    def __str__(self):
        return ""

    def __repr__(self):
        return "<Undefined %r>" % self._name

    def __bool__(self):
        return False

    def __iter__(self):
        return iter(())

    def __len__(self):
        return 0

    def __eq__(self, other):
        return isinstance(other, Undefined)

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(Undefined)


class LoopInfo(object):
    """for 循环体内的 loop 变量。"""

    __slots__ = ("index0", "index", "first", "last", "length")

    def __init__(self, index0, length):
        self.index0 = index0
        self.index = index0 + 1
        self.first = index0 == 0
        self.last = index0 == length - 1
        self.length = length


class RenderContext(object):
    """一次渲染过程的状态：变量作用域链 + 环境 + block 覆盖表。"""

    def __init__(self, env, data):
        self.env = env
        self.strict = env.strict
        self.scopes = [dict(data)]
        self.overrides = {}

    # -- 作用域 --
    def push(self, scope):
        self.scopes.append(scope)

    def pop(self):
        self.scopes.pop()

    def flatten(self):
        merged = {}
        for scope in self.scopes:
            merged.update(scope)
        return merged

    # -- 变量解析 --
    def resolve(self, name, lineno=0):
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        if self.strict:
            raise TplError(
                "undefined variable %r at line %d" % (name, lineno))
        return Undefined(name)

    def get_attr(self, obj, attr, lineno=0):
        if isinstance(obj, Undefined):
            if self.strict:
                raise TplError(
                    "cannot access attribute %r of undefined value "
                    "at line %d" % (attr, lineno))
            return obj
        found, value = _lookup(obj, attr)
        if found:
            return value
        if self.strict:
            raise TplError(
                "object of type %r has no attribute %r at line %d"
                % (type(obj).__name__, attr, lineno))
        return Undefined(attr)


def _lookup(obj, attr):
    """按 字典键 -> 序列下标 -> 对象属性 的顺序取值。"""
    if isinstance(obj, dict):
        if attr in obj:
            return True, obj[attr]
        return False, None
    if isinstance(obj, (list, tuple)) and attr.isdigit():
        index = int(attr)
        if 0 <= index < len(obj):
            return True, obj[index]
        return False, None
    if not attr.startswith("_") and hasattr(obj, attr):
        return True, getattr(obj, attr)
    return False, None
