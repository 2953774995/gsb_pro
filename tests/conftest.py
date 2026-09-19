import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from minigit import cli  # noqa: E402
from minigit.repo import find_repo  # noqa: E402


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    """A fresh initialized repository in a temp dir; cwd is moved into it."""
    monkeypatch.chdir(tmp_path)
    assert cli.main(["init"]) == 0
    return find_repo(tmp_path)


@pytest.fixture()
def run():
    """Invoke the CLI like a user would; returns (exit_code)."""
    def _run(*argv):
        return cli.main(list(argv))
    return _run


def write(root, relpath, content):
    path = os.path.join(str(root), relpath)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    mode = "wb" if isinstance(content, bytes) else "w"
    with open(path, mode) as fh:
        fh.write(content)
    return path


def read(root, relpath):
    with open(os.path.join(str(root), relpath), "r") as fh:
        return fh.read()
