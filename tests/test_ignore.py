""".minigitignore matching semantics and add/status integration."""

import os

from conftest import read_file, repo, run_cli, write_file
from minigit.ignore import IgnoreMatcher, parse_rules


def test_basic_patterns():
    m = IgnoreMatcher(parse_rules("*.log\nfoo.txt\nbuild/\n/root-only.txt\nnotes/a.md\n"))
    assert m.is_ignored("anything.log")
    assert m.is_ignored("deep/nested/x.log")
    assert m.is_ignored("foo.txt")
    assert m.is_ignored("a/foo.txt")  # basename glob at any depth
    # directory-only pattern
    assert m.is_ignored("build", is_dir=True)
    assert m.is_ignored("a/build", is_dir=True)
    assert not m.is_ignored("build", is_dir=False)
    # leading-slash basename anchors to the repository root only
    assert m.is_ignored("root-only.txt")
    assert not m.is_ignored("sub/root-only.txt")
    # a multi-segment pattern is anchored against the whole path
    assert m.is_ignored("notes/a.md")
    assert not m.is_ignored("x/notes/a.md")


def test_question_mark_and_star():
    m = IgnoreMatcher(parse_rules("file?.txt\nsrc/*.py\n"))
    assert m.is_ignored("file1.txt")
    assert not m.is_ignored("file10.txt")  # ? matches exactly one char
    # slash-free pattern matches the basename at any depth (git semantics)
    assert m.is_ignored("other/file1.txt")
    assert not m.is_ignored("other/file10.txt")
    # slash-containing pattern is anchored: * still cannot cross /
    assert m.is_ignored("src/a.py")
    assert not m.is_ignored("src/nested/a.py")
    assert not m.is_ignored("other/src/a.py")


def test_minigit_directory_always_ignored(init_repo):
    m = IgnoreMatcher.for_repo(repo())
    assert m.is_ignored(".minigit", is_dir=True)
    assert m.is_ignored(".minigit/index", is_dir=False)


def test_add_and_status_skip_ignored(init_repo):
    write_file(".minigitignore", "*.log\nbuild/\n/secret.txt\n")
    write_file("keep.txt", "1\n")
    write_file("err.log", "x\n")
    write_file("sub/err.log", "x\n")
    write_file("secret.txt", "x\n")
    write_file("notsecret/secret.txt", "x\n")  # anchored: should NOT be ignored
    write_file("build/inside.txt", "x\n")
    code, _, err = run_cli("add", ".")
    assert code == 0, err
    from minigit.index import load_index

    paths = set(load_index(repo()).entries)
    assert paths == {
        ".minigitignore", "keep.txt", "notsecret/secret.txt",
    }
    # ignored files never appear in status as untracked either
    code, out, _ = run_cli("status", "-s")
    lines = set(out.split())
    assert not any(line.endswith("err.log") for line in lines)
    assert not any(line.startswith("build") for line in lines)
    assert "secret.txt" not in lines  # anchored ignore, only root secret
    assert "notsecret/secret.txt" in lines
