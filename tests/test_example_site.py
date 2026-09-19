"""端到端：examples/ 下 extends + block + include + for + if 的多文件场景。"""

import json
import os

import pytest

from tinytpl import Environment, FileSystemLoader

EXAMPLES = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "examples")


@pytest.fixture()
def rendered():
    env = Environment(FileSystemLoader(
        os.path.join(EXAMPLES, "templates")))
    with open(os.path.join(EXAMPLES, "data.json"), encoding="utf-8") as f:
        data = json.load(f)
    return env.get_template("user_list.html").render(data)


def test_extends_and_block_override(rendered):
    assert "<title>Users - TinyTpl Demo</title>" in rendered
    assert "<h1>TinyTpl Demo</h1>" in rendered
    assert "no content" not in rendered  # block 已被覆盖


def test_include_footer(rendered):
    assert "<footer>&copy; 2026 TinyTpl Demo</footer>" in rendered


def test_for_loop_with_index(rendered):
    assert "1. Alice" in rendered
    assert "2. Bob" in rendered
    assert "3. Carol &lt;script&gt;" in rendered  # 名字被转义


def test_if_elif_else(rendered):
    assert "(admin)" in rendered
    assert rendered.count("(user)") == 2


def test_html_escaped_in_output(rendered):
    assert "&lt;b&gt;root&lt;/b&gt;" in rendered
    assert "<script>" not in rendered
