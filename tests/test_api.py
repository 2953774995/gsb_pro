"""Public API surface: Template, Environment, loaders."""

import os

import pytest

from tinytpl import (
    DictLoader,
    Environment,
    FileSystemLoader,
    Template,
    TemplateNotFound,
)


def test_template_render_kwargs():
    assert Template("{{ a }}").render(a=1) == "1"


def test_template_render_dict():
    assert Template("{{ a }}").render({"a": 2}) == "2"


def test_environment_get_template():
    env = Environment(DictLoader({"t.html": "hi {{ who }}"}))
    assert env.get_template("t.html").render({"who": "you"}) == "hi you"


def test_environment_from_string():
    env = Environment()
    assert env.from_string("{{ x }}!").render(x=1) == "1!"


def test_environment_template_cache():
    env = Environment(DictLoader({"t.html": "x"}))
    assert env.get_template("t.html") is env.get_template("t.html")


def test_dict_loader_missing():
    loader = DictLoader({})
    with pytest.raises(TemplateNotFound):
        loader.get_source("nope.html")


def test_filesystem_loader(tmp_path):
    (tmp_path / "hello.html").write_text("Hello {{ name }}", encoding="utf-8")
    env = Environment(FileSystemLoader(str(tmp_path)))
    assert env.get_template("hello.html").render(name="fs") == "Hello fs"


def test_filesystem_loader_missing(tmp_path):
    env = Environment(FileSystemLoader(str(tmp_path)))
    with pytest.raises(TemplateNotFound):
        env.get_template("missing.html")


def test_filesystem_loader_blocks_path_escape(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP SECRET", encoding="utf-8")
    sub = tmp_path / "templates"
    sub.mkdir()
    env = Environment(FileSystemLoader(str(sub)))
    with pytest.raises(TemplateNotFound):
        env.get_template(os.path.join("..", "secret.txt"))


def test_filesystem_loader_multiple_paths(tmp_path):
    d1 = tmp_path / "a"
    d2 = tmp_path / "b"
    d1.mkdir()
    d2.mkdir()
    (d2 / "t.html").write_text("from b", encoding="utf-8")
    env = Environment(FileSystemLoader([str(d1), str(d2)]))
    assert env.get_template("t.html").render() == "from b"


def test_custom_filter():
    env = Environment(filters={"double": lambda v: v * 2})
    assert env.from_string("{{ n | double }}").render(n=3) == "6"


def test_strict_via_template_argument():
    with pytest.raises(Exception):
        Template("{{ missing }}", strict=True).render()
