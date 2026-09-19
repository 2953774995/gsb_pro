"""Shared pytest fixtures/helpers.

Every test operates inside pytest's ``tmp_path`` so the surrounding
environment is never polluted.
"""

import os
import sys

import pytest

# Make the package importable when tests run from a fresh checkout
# (``python3 -m pytest tests/`` from the repo root also works without this).
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from minigit.cli import main as cli_main  # noqa: E402
from minigit.repository import Repository  # noqa: E402


@pytest.fixture(autouse=True)
def _fixed_identity(monkeypatch):
    """Deterministic author/committer identity and timestamp."""
    monkeypatch.setenv("MINIGIT_AUTHOR_NAME", "Test User")
    monkeypatch.setenv("MINIGIT_AUTHOR_EMAIL", "test@example.com")
    monkeypatch.setenv("MINIGIT_AUTHOR_DATE", "1700000000 +0800")
    yield


@pytest.fixture
def repo_dir(tmp_path, monkeypatch):
    """chdir into an empty temp directory; return its ``pathlib.Path``."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def init_repo(repo_dir):
    """chdir into a temp directory that already has ``minigit init``."""
    assert cli_main(["init"]) == 0
    return repo_dir


def run_cli(*argv):
    """Run the CLI in-process and return ``(returncode, stdout, stderr)``."""
    import io
    import contextlib

    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli_main(list(argv))
    return code, out.getvalue(), err.getvalue()


def repo():
    return Repository.find()


def write_file(path, content, encoding=None):
    """Write text/bytes to a path (relative to cwd), creating parents."""
    d = os.path.dirname(str(path))
    if d:
        os.makedirs(d, exist_ok=True)
    mode = "wb" if isinstance(content, bytes) else "w"
    kwargs = {} if isinstance(content, bytes) else {"encoding": "utf-8"}
    with open(str(path), mode, **kwargs) as fh:
        fh.write(content)


def read_file(path):
    with open(str(path), "rb") as fh:
        return fh.read()
