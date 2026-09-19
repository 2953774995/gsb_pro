import ast
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "minidiff"
LAUNCHER = ROOT / "minidiff-cli"
FORBIDDEN_MODULES = {"difflib", "subprocess", "shutil"}


def imported_modules(tree):
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".")[0])
    return modules


def test_implementation_uses_only_stdlib_and_no_core_helpers():
    assert not list(PACKAGE.rglob("requirements*.txt"))
    assert not list(ROOT.glob("requirements*.txt"))
    # pytest may be used only by tests, never imported by implementation.
    for path in list(PACKAGE.rglob("*.py")) + [LAUNCHER]:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        modules = imported_modules(tree)
        assert "pytest" not in modules
        assert not modules.intersection(FORBIDDEN_MODULES), (path, modules)

        # Guard against shelling out through os.system, subprocess.Popen, or
        # os.exec* process launch APIs.
        for node in ast.walk(tree):
            assert not (
                isinstance(node, ast.Attribute)
                and node.attr in {"system", "popen", "Popen"}
            )
            assert not (
                isinstance(node, ast.Attribute)
                and node.attr.startswith("exec")
                and isinstance(node.value, ast.Name)
                and node.value.id == "os"
            )


def test_pyproject_has_no_runtime_dependencies():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "dependencies = []" in pyproject
    assert "pytest" not in pyproject


def test_module_imports_with_clean_environment():
    env = os.environ.copy()
    old_path = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(ROOT) + (os.pathsep + old_path if old_path else "")
    result = subprocess.run(
        [sys.executable, "-c", "import minidiff; print(minidiff.__version__)"],
        cwd="/tmp",
        env=env,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip()
