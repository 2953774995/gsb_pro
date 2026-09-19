"""模板 AST 节点：每种节点知道如何把自己渲染到输出缓冲。"""

from .errors import TplError
from .escape import escape
from .renderer import LoopInfo, Undefined


def render_nodes(nodes, rc, out):
    for node in nodes:
        node.render(rc, out)


class Node(object):
    __slots__ = ("lineno",)

    def __init__(self, lineno):
        self.lineno = lineno

    def render(self, rc, out):  # pragma: no cover - 抽象接口
        raise NotImplementedError


class TextNode(Node):
    __slots__ = ("text",)

    def __init__(self, text, lineno):
        super().__init__(lineno)
        self.text = text

    def render(self, rc, out):
        out.append(self.text)


class VarNode(Node):
    __slots__ = ("expr", "raw")

    def __init__(self, expr, raw, lineno):
        super().__init__(lineno)
        self.expr = expr
        self.raw = raw

    def render(self, rc, out):
        value = self.expr.eval(rc)
        if self.raw:
            out.append(str(value))
        else:
            out.append(escape(value))


class IfNode(Node):
    __slots__ = ("branches", "else_body")

    def __init__(self, branches, else_body, lineno):
        super().__init__(lineno)
        self.branches = branches      # [(cond_expr, body_nodes), ...]
        self.else_body = else_body

    def render(self, rc, out):
        for cond, body in self.branches:
            if cond.eval(rc):
                rc.push({})
                render_nodes(body, rc, out)
                rc.pop()
                return
        if self.else_body:
            rc.push({})
            render_nodes(self.else_body, rc, out)
            rc.pop()


class ForNode(Node):
    __slots__ = ("var_name", "iter_expr", "body")

    def __init__(self, var_name, iter_expr, body, lineno):
        super().__init__(lineno)
        self.var_name = var_name
        self.iter_expr = iter_expr
        self.body = body

    def render(self, rc, out):
        iterable = self.iter_expr.eval(rc)
        if isinstance(iterable, Undefined):
            iterable = ()
        try:
            items = list(iterable)
        except TypeError:
            raise TplError(
                "value of type %r is not iterable at line %d"
                % (type(iterable).__name__, self.lineno))
        length = len(items)
        for index0, item in enumerate(items):
            rc.push({
                self.var_name: item,
                "loop": LoopInfo(index0, length),
            })
            render_nodes(self.body, rc, out)
            rc.pop()


class BlockNode(Node):
    __slots__ = ("name", "body")

    def __init__(self, name, body, lineno):
        super().__init__(lineno)
        self.name = name
        self.body = body

    def render(self, rc, out):
        override = rc.overrides.get(self.name)
        if override is not None and override is not self:
            render_nodes(override.body, rc, out)
        else:
            render_nodes(self.body, rc, out)


class ExtendsNode(Node):
    """仅作为模板级元数据存在，渲染由 Template 驱动。"""

    __slots__ = ("name_expr",)

    def __init__(self, name_expr, lineno):
        super().__init__(lineno)
        self.name_expr = name_expr

    def render(self, rc, out):
        pass


class IncludeNode(Node):
    __slots__ = ("name_expr",)

    def __init__(self, name_expr, lineno):
        super().__init__(lineno)
        self.name_expr = name_expr

    def render(self, rc, out):
        name = self.name_expr.eval(rc)
        if not isinstance(name, str):
            raise TplError(
                "include expects a template name string at line %d"
                % self.lineno)
        template = rc.env.get_template(name)
        out.append(template.render(rc.flatten()))
