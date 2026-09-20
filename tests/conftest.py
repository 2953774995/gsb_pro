import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from minigit import cli  # noqa: E402


def run(*argv):
    """Invoke the minigit CLI in-process; returns the exit code."""
    return cli.main(list(argv))


def write(root, relpath, content):
    path = root / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")


def head_sha(repo):
    branch = (repo / ".minigit" / "HEAD").read_text().strip()
    assert branch.startswith("ref: refs/heads/")
    ref = repo / ".minigit" / branch[len("ref: "):]
    return ref.read_text().strip()


def list_objects(repo):
    result = []
    objects_dir = repo / ".minigit" / "objects"
    for sub in sorted(objects_dir.iterdir()):
        if sub.is_dir():
            for f in sorted(sub.iterdir()):
                result.append(sub.name + f.name)
    return result


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    """An empty temporary directory used as cwd."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def repo(workdir):
    """A fresh minigit repository in a temporary directory."""
    assert run("init") == 0
    return workdir
