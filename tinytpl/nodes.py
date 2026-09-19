"""AST nodes and the render context."""

from .errors import TplError
from .escape import SafeString, escape_html
from .expression import eval_expr


# ---------------------------------------------------------------------------
# Undefined values
# ---------------------------------------------------------------------------


class Undefined(object):
    """Placeholder for missing variables (default mode: renders as '')."""

    def __init__(self, name):
        self._name = name

    def __str__(self):
        return ""

    def __repr__(self):
        return "Undefined(%r)" % self._name

    def __bool__(self):
        return False

    def __iter__(self):
        return iter(())

    def __len__(self):
        return 0


class StrictUndefined(Undefined):
    """Missing variable in strict mode: any use raises TplError."""

    def _fail(self):
        raise TplError("undefined variable: %r" % self._name)

    def __str__(self):
        self._fail()

    def __bool__(self):
        self._fail()

    def __iter__(self):
        self._fail()

    def __len__(self):
        self._fail()

    def __eq__(self, other):
        self._fail()

    def __ne__(self, other):
        self._fail()


class LoopInfo(object):
    """The ``loop`` variable available inside for blocks."""

    __slots__ = ("index0", "length")

    def __init__(self, index0, length):
        self.index0 = index0
        self.length = length

    @property
    def index(self):
        return self.index0 + 1

    @property
    def first(self):
        return self.index0 == 0

    @property
    def last(self):
        return self.index0 == self.length - 1


# ---------------------------------------------------------------------------
# Render context (lexical scoping via a scope stack)
# ---------------------------------------------------------------------------


class RenderContext(object):
    def __init__(self, env, data, blocks=None, stack=None):
        self.env = env
        self.scopes = [dict(data)]
        self.blocks = blocks if blocks is not None else {}
        self.stack = stack if stack is not None else []

    def derive(self, blocks=None):
        """New context sharing scopes, used when crossing template boundaries."""
        return RenderContext.__new_derived(self, blocks)

    @staticmethod
    def __new_derived(ctx, blocks):
        new = object.__new__(RenderContext)
        new.env = ctx.env
        new.scopes = ctx.scopes
        new.blocks = ctx.blocks if blocks is None else blocks
        new.stack = ctx.stack
        return new

    def push(self, mapping):
        self.scopes.append(mapping)

    def pop(self):
        self.scopes.pop()

    def resolve(self, name):
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        return self.env.make_undefined(name)

    def get_attr(self, obj, segment):
        if isinstance(obj, Undefined):
            if isinstance(obj, StrictUndefined):
                raise TplError("undefined variable: %r" % obj._name)
            return self.env.make_undefined(segment)
        if isinstance(obj, dict) and segment in obj:
            return obj[segment]
        if segment.isdigit() and isinstance(obj, (list, tuple, str)):
            idx = int(segment)
            if 0 <= idx < len(obj):
                return obj[idx]
            return self.env.make_undefined(segment)
        if not segment.startswith("_") and hasattr(obj, segment):
            return getattr(obj, segment)
        return self.env.make_undefined(segment)


# ---------------------------------------------------------------------------
# AST nodes
# ---------------------------------------------------------------------------


def render_nodes(nodes, ctx, out):
    for node in nodes:
        node.render(ctx, out)


class TextNode(object):
    def __init__(self, text):
        self.text = text

    def render(self, ctx, out):
        out.append(self.text)


class OutputNode(object):
    def __init__(self, expr, filters, line=None):
        self.expr = expr
        self.filters = filters
        self.line = line

    def render(self, ctx, out):
        try:
            value = eval_expr(self.expr, ctx)
        except TplError as exc:
            if exc.line is None and self.line is not None:
                exc.line = self.line
                exc.args = (str(exc),)
            raise
        for fname in self.filters:
            func = ctx.env.filters.get(fname)
            if func is None:
                raise TplError("unknown filter: %r" % fname, line=self.line)
            value = func(value)
        if isinstance(value, SafeString):
            out.append(str(value))
        elif value is None:
            out.append("")
        else:
            out.append(escape_html(value))


class IfNode(object):
    def __init__(self, branches, else_body):
        self.branches = branches  # list of (cond_expr, body_nodes)
        self.else_body = else_body

    def render(self, ctx, out):
        for cond, body in self.branches:
            if eval_expr(cond, ctx):
                ctx.push({})
                try:
                    render_nodes(body, ctx, out)
                finally:
                    ctx.pop()
                return
        if self.else_body is not None:
            ctx.push({})
            try:
                render_nodes(self.else_body, ctx, out)
            finally:
                ctx.pop()


class ForNode(object):
    def __init__(self, var_name, iter_expr, body, line=None):
        self.var_name = var_name
        self.iter_expr = iter_expr
        self.body = body
        self.line = line

    def render(self, ctx, out):
        iterable = eval_expr(self.iter_expr, ctx)
        if isinstance(iterable, Undefined):
            items = []  # strict mode raises on iter() below
        try:
            items = list(iterable)
        except TplError:
            raise
        except TypeError:
            raise TplError(
                "value is not iterable in for loop", line=self.line
            )
        length = len(items)
        for index0, item in enumerate(items):
            # loop variable and `loop` live in their own scope and never leak
            ctx.push({self.var_name: item, "loop": LoopInfo(index0, length)})
            try:
                render_nodes(self.body, ctx, out)
            finally:
                ctx.pop()


class BlockNode(object):
    def __init__(self, name, body, line=None):
        self.name = name
        self.body = body
        self.line = line

    def render(self, ctx, out):
        override = ctx.blocks.get(self.name)
        if override is not None and override is not self:
            render_nodes(override.body, ctx, out)
        else:
            render_nodes(self.body, ctx, out)


class ExtendsNode(object):
    def __init__(self, expr, line=None):
        self.expr = expr
        self.line = line

    def render(self, ctx, out):  # handled by Template._render
        pass


class IncludeNode(object):
    def __init__(self, expr, line=None):
        self.expr = expr
        self.line = line

    def render(self, ctx, out):
        name = eval_expr(self.expr, ctx)
        if not isinstance(name, str):
            raise TplError(
                "include expects a template name string", line=self.line
            )
        template = ctx.env.get_template(name)
        out.append(template._render_with_stack(ctx, self.line))
