"""Template：编译后的模板，可反复渲染。"""

from .errors import TplError
from .nodes import render_nodes
from .parser import parse
from .renderer import RenderContext
from .tokenizer import tokenize


class Template(object):
    def __init__(self, source, loader=None, strict=False, env=None,
                 name=None):
        if env is None:
            from .environment import Environment
            env = Environment(loader=loader, strict=strict)
        self.env = env
        self.name = name
        self.nodes, self.extends, self.blocks = parse(tokenize(source))

    def render(self, context=None, **kwargs):
        """渲染模板。context 可为 dict，也可用关键字参数传入。"""
        data = {}
        if context is not None:
            if not isinstance(context, dict):
                raise TplError("render context must be a dict, got %r"
                               % type(context).__name__)
            data.update(context)
        data.update(kwargs)
        rc = RenderContext(self.env, data)
        out = []
        self._render(rc, out)
        return "".join(out)

    def _render(self, rc, out):
        if self.extends is not None:
            parent_name = self.extends.name_expr.eval(rc)
            if not isinstance(parent_name, str):
                raise TplError(
                    "extends expects a template name string at line %d"
                    % self.extends.lineno)
            parent = self.env.get_template(parent_name)
            saved = rc.overrides
            # 更下层（更具体的子类）的 block 覆盖优先
            merged = dict(self.blocks)
            merged.update(saved)
            rc.overrides = merged
            try:
                parent._render(rc, out)
            finally:
                rc.overrides = saved
        else:
            render_nodes(self.nodes, rc, out)
