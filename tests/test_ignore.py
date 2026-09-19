import os

from minigit.ignore import IgnoreRules

from conftest import write


def rules(*lines):
    r = IgnoreRules()
    for line in lines:
        r.add(line)
    return r


def test_star_and_question_mark():
    r = rules("*.log", "file?.txt")
    assert r.matches("debug.log")
    assert r.matches("sub/dir/error.log")
    assert r.matches("file1.txt")
    assert not r.matches("file12.txt")
    assert not r.matches("readme.md")


def test_directory_pattern():
    r = rules("build/")
    assert r.matches("build", is_dir=True)
    assert not r.matches("build", is_dir=False)
    assert not r.matches("buildozer", is_dir=True)


def test_anchored_and_nested_patterns():
    r = rules("/root.txt", "docs/*.tmp")
    assert r.matches("root.txt")
    assert not r.matches("sub/root.txt")
    assert r.matches("docs/x.tmp")
    assert not r.matches("other/docs/x.tmp")


def test_negation():
    r = rules("*.log", "!keep.log")
    assert r.matches("a.log")
    assert not r.matches("keep.log")


def test_comments_and_blank_lines():
    r = rules("# comment", "", "  ", "*.pyc")
    assert r.matches("x.pyc")
    assert not r.matches("# comment")


def test_minigit_dir_always_ignored():
    r = rules()
    assert r.matches(".minigit", is_dir=True)
    assert r.matches(".minigit/objects/ab", is_dir=True)


def test_add_and_status_skip_ignored(repo, run, capsys):
    write(repo.root, ".minigitignore", "*.log\nbuild/\n")
    write(repo.root, "keep.txt", "keep")
    write(repo.root, "debug.log", "ignored")
    write(repo.root, "build/out.bin", "ignored")
    assert run("add", ".") == 0
    assert run("status") == 0
    out = capsys.readouterr().out
    assert "debug.log" not in out
    assert "out.bin" not in out
    assert "keep.txt" in out
    assert ".minigitignore" in out  # the ignore file itself is trackable

    from minigit.index import read_index
    entries = read_index(repo)
    assert "keep.txt" in entries
    assert "debug.log" not in entries
    assert "build/out.bin" not in entries


def test_minigit_dir_never_indexed(repo, run):
    write(repo.root, "a.txt", "x")
    assert run("add", ".") == 0
    from minigit.index import read_index
    for path in read_index(repo):
        assert not path.startswith(".minigit")
