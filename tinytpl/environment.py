"""Environment：持有 loader 与渲染配置，负责模板的获取与缓存。"""

from .loader import DictLoader


class Environment(object):
    def __init__(self, loader=None, strict=False):
        self.loader = loader if loader is not None else DictLoader({})
        self.strict = strict
        self._cache = {}

    def get_template(self, name):
        """按名字加载并编译模板（带缓存）。模板不存在时抛 TplError。"""
        if name in self._cache:
            return self._cache[name]
        source = self.loader.load(name)
        from .template import Template
        template = Template(source, env=self, name=name)
        self._cache[name] = template
        return template

    def from_string(self, source):
        """直接从源码字符串创建模板。"""
        from .template import Template
        return Template(source, env=self)
