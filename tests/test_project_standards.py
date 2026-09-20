from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _imported_roots(path: Path):
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.module.split(".")[0]


def test_runtime_code_uses_python_standard_library_only():
    allowed = {
        "__future__",
        "argparse",
        "dataclasses",
        "datetime",
        "difflib",
        "getpass",
        "hashlib",
        "os",
        "pathlib",
        "re",
        "shutil",
        "stat",
        "sys",
        "tempfile",
        "time",
        "typing",
        "zlib",
        "cfgvault",
    }
    for path in (ROOT / "cfgvault").glob("*.py"):
        for root in _imported_roots(path):
            assert root in allowed, f"{path.name} imports {root}"
        text = path.read_text()
        assert "subprocess" not in text
        assert "os.system" not in text
        assert "popen" not in text
