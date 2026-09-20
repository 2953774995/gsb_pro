from __future__ import annotations

import os
import shutil
import tempfile

import pytest

from cfgvault.cli import main as cli_main


@pytest.fixture(autouse=True)
def deterministic_environment(monkeypatch):
    monkeypatch.setenv("CFGVULT_AUTHOR_NAME", "Operator")
    monkeypatch.setenv("CFGVULT_AUTHOR_EMAIL", "ops@example.com")
    monkeypatch.setenv("CFGVULT_AUTHOR_DATE", "1700000000")
    monkeypatch.delenv("USER", raising=False)
    # pytest normally writes its cache outside tmp_path; do not leave cfgvault
    # pycache files in the source checkout during these tests.
    cache_prefix = os.path.join(tempfile.gettempdir(), "cfgvault-test-pycache")
    shutil.rmtree(cache_prefix, ignore_errors=True)
    monkeypatch.setenv("PYTHONPYCACHEPREFIX", cache_prefix)


@pytest.fixture
def run_cli(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    def _run(*argv):
        code = cli_main(argv)
        captured = capsys.readouterr()
        return type("Result", (), {
            "code": code,
            "stdout": captured.out,
            "stderr": captured.err,
        })

    return _run


@pytest.fixture
def in_tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def write(path, text="", binary=None):
    path = os.fspath(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    data = binary if binary is not None else text.encode("utf-8")
    with open(path, "wb") as stream:
        stream.write(data)
    return path
