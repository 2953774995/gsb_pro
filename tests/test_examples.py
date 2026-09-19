"""Render the multi-file example scenario (extends + block + include + for + if)."""

import json
import os

from tinytpl import Environment, FileSystemLoader

EXAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples")


def render_example():
    env = Environment(FileSystemLoader(os.path.join(EXAMPLES, "templates")))
    with open(os.path.join(EXAMPLES, "data.json"), encoding="utf-8") as fh:
        data = json.load(fh)
    return env.get_template("catalog.html").render(data)


def test_example_renders_expected_output():
    out = render_example()
    # block overrides from the child template
    assert "<title>Tiny &amp; Co Catalog</title>" in out
    assert "<h1>Tiny &amp; Co</h1>" in out
    # include + for + loop variables
    assert "1. Apple &lt;organic&gt; - $3" in out
    assert "2. Bread - $5" in out
    assert "3. Cheese &amp; Wine - $12" in out
    # if inside the loop
    assert "(SALE!)" in out
    assert 'class="first"' in out
    # filters and expressions
    assert "Total: 3 products, min price: $5" in out


def test_example_html_escaping():
    out = render_example()
    assert "Apple <organic>" not in out
    assert "Cheese & Wine" not in out
