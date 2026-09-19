import os

import pytest

from minigit.cli import main


@pytest.fixture(autouse=True)
def deterministic_author(monkeypatch):
    monkeypatch.setenv("MINIGIT_AUTHOR_NAME", "Test User")
    monkeypatch.setenv("MINIGIT_AUTHOR_EMAIL", "test@example.com")


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["init"]) == 0
    return tmp_path


def run(*args, expect=0):
    code = main(list(args))
    assert code == expect
    return code


def write(path, content=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def commit_all(message):
    return run("add", ".") and run("commit", "-m", message)
