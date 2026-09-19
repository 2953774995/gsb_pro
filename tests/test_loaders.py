"""loader：字典与文件系统。"""

import pytest

from tinytpl import DictLoader, Environment, FileSystemLoader, TplError


def test_dict_loader():
    env = Environment(DictLoader({"a": "A-{{ x }}"}))
    assert env.get_template("a").render(x=1) == "A-1"


def test_dict_loader_missing():
    with pytest.raises(TplError):
        DictLoader({}).load("nope")


def test_filesystem_loader(tmp_path):
    (tmp_path / "hello.html").write_text("Hi {{ name }}", encoding="utf-8")
    env = Environment(FileSystemLoader(str(tmp_path)))
    assert env.get_template("hello.html").render(name="Z") == "Hi Z"


def test_filesystem_loader_missing(tmp_path):
    env = Environment(FileSystemLoader(str(tmp_path)))
    with pytest.raises(TplError, match="template not found"):
        env.get_template("absent.html")


def test_filesystem_loader_multiple_paths(tmp_path):
    d1 = tmp_path / "one"
    d2 = tmp_path / "two"
    d1.mkdir()
    d2.mkdir()
    (d2 / "t.html").write_text("from-two", encoding="utf-8")
    env = Environment(FileSystemLoader([str(d1), str(d2)]))
    assert env.get_template("t.html").render() == "from-two"


def test_template_cache(tmp_path):
    f = tmp_path / "c.html"
    f.write_text("v1", encoding="utf-8")
    env = Environment(FileSystemLoader(str(tmp_path)))
    assert env.get_template("c.html").render() == "v1"
    f.write_text("v2", encoding="utf-8")
    # 缓存生效：同一 Environment 内仍是 v1
    assert env.get_template("c.html").render() == "v1"


def test_from_string():
    env = Environment()
    assert env.from_string("{{ 1 + 1 }}").render() == "2"
