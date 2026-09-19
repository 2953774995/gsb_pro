"""模板加载器：从字典或文件系统目录读取模板源码。"""

import os

from .errors import TplError


class DictLoader:
    """从 {name: source} 字典中加载模板。"""

    def __init__(self, mapping):
        self.mapping = dict(mapping)

    def load(self, name):
        try:
            return self.mapping[name]
        except KeyError:
            raise TplError("template not found: %r" % name)


class FileSystemLoader:
    """从一个或多个目录中加载模板文件。"""

    def __init__(self, paths):
        if isinstance(paths, (str, os.PathLike)):
            paths = [paths]
        self.paths = [os.fspath(p) for p in paths]

    def load(self, name):
        for base in self.paths:
            path = os.path.normpath(os.path.join(base, name))
            # 防止 ../ 路径穿越出模板目录
            if not (path + os.sep).startswith(os.path.normpath(base) + os.sep) \
                    and path != os.path.normpath(base):
                continue
            if os.path.isfile(path):
                with open(path, "r", encoding="utf-8") as f:
                    return f.read()
        raise TplError("template not found: %r" % name)
