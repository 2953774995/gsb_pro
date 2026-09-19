"""Prove the implementation does not use the stdlib ``re`` module."""

import subprocess
import sys
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent.parent / "regexlab"


def _source_files():
    return sorted(PACKAGE_DIR.glob("*.py"))


def test_package_files_exist():
    assert _source_files(), "no source files found in regexlab/"


def test_no_import_of_re_in_sources():
    for path in _source_files():
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            assert not stripped.startswith("import re"), \
                "%s:%d imports re" % (path, lineno)
            assert not stripped.startswith("from re"), \
                "%s:%d imports from re" % (path, lineno)
            assert "import re " not in stripped, \
                "%s:%d imports re" % (path, lineno)


def test_re_not_loaded_after_importing_regexlab():
    # In a fresh interpreter, importing regexlab must not pull in 're'.
    code = (
        "import sys; "
        "import regexlab; "
        "regexlab.search('a+', 'aaa'); "
        "assert 're' not in sys.modules, "
        "'re module was loaded by regexlab'; "
        "print('re not loaded')"
    )
    result = subprocess.run([sys.executable, "-c", code],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "re not loaded" in result.stdout
