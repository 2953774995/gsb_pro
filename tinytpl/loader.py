"""Template loaders: read template sources from dicts or directories."""

import os

from .errors import TemplateNotFound


class DictLoader(object):
    """Load templates from an in-memory ``{name: source}`` mapping."""

    def __init__(self, mapping):
        self.mapping = dict(mapping)

    def get_source(self, name):
        try:
            return self.mapping[name]
        except KeyError:
            raise TemplateNotFound(name)


class FileSystemLoader(object):
    """Load templates from one or more directories.

    Template names are relative paths; ``..`` escapes outside the search
    directories are rejected.
    """

    def __init__(self, search_paths):
        if isinstance(search_paths, str):
            search_paths = [search_paths]
        self.search_paths = [os.path.abspath(p) for p in search_paths]

    def get_source(self, name):
        for base in self.search_paths:
            full = os.path.normpath(os.path.join(base, name))
            if full != base and not full.startswith(base + os.sep):
                continue  # path escapes the search root
            if os.path.isfile(full):
                with open(full, "r", encoding="utf-8") as fh:
                    return fh.read()
        raise TemplateNotFound(name)
