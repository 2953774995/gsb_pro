"""Environment and Template: the public rendering API."""

from .errors import TplError
from .escape import SafeString, escape_html, mark_safe
from .expression import eval_expr
from .loader import DictLoader
from .nodes import (
    BlockNode,
    ExtendsNode,
    RenderContext,
    StrictUndefined,
    Undefined,
    render_nodes,
)
from .parser import parse
from .tokenizer import tokenize


# ---------------------------------------------------------------------------
# Built-in filters
# ---------------------------------------------------------------------------


def _filter_raw(value):
    if value is None:
        return SafeString("")
    return mark_safe(str(value))


def _filter_escape(value):
    if value is None:
        return SafeString("")
    return mark_safe(escape_html(value))


def _filter_upper(value):
    return str(value).upper()


def _filter_lower(value):
    return str(value).lower()


def _filter_length(value):
    return len(value)


DEFAULT_FILTERS = {
    "raw": _filter_raw,
    "escape": _filter_escape,
    "e": _filter_escape,
    "upper": _filter_upper,
    "lower": _filter_lower,
    "length": _filter_length,
}


# ---------------------------------------------------------------------------
# Template
# ---------------------------------------------------------------------------


class Template(object):
    """A compiled template.

    Usage::

        Template("Hello {{ name }}!").render(name="world")
        Template(src, loader=DictLoader({...}), strict=True).render(**ctx)
    """

    def __init__(self, source, loader=None, name=None, strict=False,
                 environment=None):
        if environment is None:
            environment = Environment(loader=loader, strict=strict)
        self.env = environment
        self.name = name
        self.source = source
        self.nodes = parse(tokenize(source, template=name), template=name)

        extends = [n for n in self.nodes if isinstance(n, ExtendsNode)]
        if len(extends) > 1:
            raise TplError(
                "multiple {% extends %} tags are not allowed",
                line=extends[1].line,
                template=name,
            )
        self.extends_node = extends[0] if extends else None

        # Collect blocks (including nested ones); duplicate names are an error.
        self.blocks = {}
        self._collect_blocks(self.nodes)

    def _collect_blocks(self, node_list):
        for node in node_list:
            if isinstance(node, BlockNode):
                if node.name in self.blocks:
                    raise TplError(
                        "duplicate block name: %r" % node.name,
                        line=node.line,
                        template=self.name,
                    )
                self.blocks[node.name] = node
                self._collect_blocks(node.body)
            else:
                for attr in ("body", "else_body"):
                    child = getattr(node, attr, None)
                    if child:
                        self._collect_blocks(child)
                for _, branch_body in getattr(node, "branches", []):
                    self._collect_blocks(branch_body)

    # -- rendering ----------------------------------------------------------

    def render(self, context=None, **kwargs):
        """Render the template. Accepts a dict and/or keyword arguments."""
        data = {}
        if context:
            data.update(context)
        data.update(kwargs)
        ctx = RenderContext(self.env, data)
        return self._render(ctx)

    def _render_with_stack(self, ctx, line=None):
        key = self.name if self.name is not None else id(self)
        if key in ctx.stack:
            chain = " -> ".join(str(k) for k in ctx.stack + [key])
            raise TplError("circular template reference: %s" % chain, line=line)
        ctx.stack.append(key)
        try:
            return self._render(ctx)
        finally:
            ctx.stack.pop()

    def _render(self, ctx):
        if self.extends_node is not None:
            parent_name = eval_expr(self.extends_node.expr, ctx)
            if not isinstance(parent_name, str):
                raise TplError(
                    "extends expects a template name string",
                    line=self.extends_node.line,
                    template=self.name,
                )
            parent = self.env.get_template(parent_name)
            # Child blocks override the parent's; blocks already in
            # ctx.blocks (from even more derived templates) win.
            blocks = dict(self.blocks)
            blocks.update(ctx.blocks)
            sub = ctx.derive(blocks=blocks)
            return parent._render_with_stack(sub, self.extends_node.line)
        out = []
        render_nodes(self.nodes, ctx, out)
        return "".join(out)


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------


class Environment(object):
    """Holds a loader, filters and undefined-variable policy.

    Usage::

        env = Environment(loader=FileSystemLoader("templates"))
        env.get_template("page.html").render({"name": "world"})
    """

    def __init__(self, loader=None, strict=False, filters=None):
        self.loader = loader if loader is not None else DictLoader({})
        self.strict = strict
        self.filters = dict(DEFAULT_FILTERS)
        if filters:
            self.filters.update(filters)
        self._cache = {}

    def make_undefined(self, name):
        if self.strict:
            return StrictUndefined(name)
        return Undefined(name)

    def get_template(self, name):
        if name in self._cache:
            return self._cache[name]
        source = self.loader.get_source(name)  # raises TemplateNotFound
        template = Template(source, name=name, environment=self)
        self._cache[name] = template
        return template

    def from_string(self, source, name=None):
        return Template(source, name=name, environment=self)
