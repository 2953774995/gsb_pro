import os
import re
from pathlib import Path

import pytest

from mdsite.builder import MdsiteError, build


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_end_to_end_build_structure_toc_assets_and_links(tmp_path):
    src = tmp_path / "docs"
    guide = src / "guide"
    guide.mkdir(parents=True)

    (src / "index.md").write_text(
        "# 首页\n\n## 开始\n\n跳转到[指南](guide/install.md#安装)。\n\n"
        "### 中文小节\n\n![图](assets/demo.png)\n",
        encoding="utf-8",
    )
    (guide / "install.md").write_text(
        "# 安装指南\n\n## 安装\n\n### Python\n\n- a\n  - b\n\n"
        "[首页](../index.md)\n",
        encoding="utf-8",
    )
    assets = src / "assets"
    assets.mkdir()
    (assets / "demo.png").write_bytes(b"png")

    out = tmp_path / "site"
    count = build(src, out, theme="dark", site_name="Docs")

    assert count == 2
    assert (out / "index.html").is_file()
    assert (out / "guide" / "install.html").is_file()
    assert (out / "assets" / "demo.png").read_bytes() == b"png"
    assert (out / "assets" / "style.css").is_file()
    assert (out / "assets" / "default.css").is_file()
    assert (out / "assets" / "dark.css").is_file()

    index = _read(out / "index.html")
    install = _read(out / "guide" / "install.html")

    assert "{{" not in index and "}}" not in index
    assert "{%" not in index and "%}" not in index
    assert 'href="guide/install.html#安装"' in index
    assert 'href="../index.html"' in install
    assert 'src="assets/demo.png"' in index
    assert '<link rel="stylesheet" href="../assets/style.css">' in install

    heading_id = re.search(r'<h3 id="([^"]+)">中文小节</h3>', index).group(1)
    assert f'<a href="#{heading_id}">中文小节</a>' in index
    assert heading_id == "中文小节"

    h2_id = re.search(r'<h2 id="([^"]+)">安装</h2>', install).group(1)
    assert f'<a href="#{h2_id}">安装</a>' in install
    assert "<ul><li>a<ul><li>b</li></ul></li></ul>" in install


def test_auto_index_for_documents_without_index(tmp_path):
    src = tmp_path / "docs"
    src.mkdir()
    (src / "only.md").write_text("# Only\n\n## Section\n", encoding="utf-8")
    out = tmp_path / "site"
    build(src, out)
    index = _read(out / "index.html")
    assert 'href="only.html"' in index
    assert "Only" in index


def test_relative_markdown_links_do_not_touch_block_html(tmp_path):
    src = tmp_path / "docs"
    src.mkdir()
    (src / "index.md").write_text(
        "# Link\n\n[md](other.md)\n\n<a href=\"other.md\">raw</a>\n",
        encoding="utf-8",
    )
    out = tmp_path / "site"
    build(src, out)
    html = _read(out / "index.html")
    assert 'href="other.html"' in html
    assert '<a href="other.md">raw</a>' in html
    assert "data-md-link" not in html


def test_missing_input_directory_has_friendly_error(tmp_path):
    with pytest.raises(MdsiteError, match="输入目录不存在"):
        build(tmp_path / "missing", tmp_path / "out")


def test_input_path_that_is_file_has_friendly_error(tmp_path):
    path = tmp_path / "file.md"
    path.write_text("# x", encoding="utf-8")
    with pytest.raises(MdsiteError, match="输入路径不是目录"):
        build(path, tmp_path / "out")


def test_unknown_theme_has_friendly_error(tmp_path):
    src = tmp_path / "docs"
    src.mkdir()
    with pytest.raises(MdsiteError, match="未知主题"):
        build(src, tmp_path / "out", theme="nope")


@pytest.mark.skipif(os.geteuid() == 0, reason="root can read chmod 000 files")
def test_unreadable_file_has_friendly_error(tmp_path):
    src = tmp_path / "docs"
    src.mkdir()
    bad = src / "bad.md"
    bad.write_text("# bad", encoding="utf-8")
    bad.chmod(0)
    try:
        with pytest.raises(MdsiteError, match="无法读取文件"):
            build(src, tmp_path / "out")
    finally:
        bad.chmod(0o644)


def test_invalid_utf8_file_has_friendly_error(tmp_path):
    src = tmp_path / "docs"
    src.mkdir()
    (src / "bad.md").write_bytes(b"\xff\xfe\x00")
    with pytest.raises(MdsiteError, match="不是有效的 UTF-8"):
        build(src, tmp_path / "out")
