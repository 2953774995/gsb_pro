"""Guard the constraints of the task:

* the implementation must not import ``difflib`` at all (the core
  algorithm is hand-written LCS);
* the implementation must not shell out to system ``diff``/``patch``;
* the implementation must only rely on the Python standard library.
"""

import ast
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "minidiff"

SOURCE_FILES = sorted(PACKAGE.glob("*.py"))


def imported_modules(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module \
                and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def test_difflib_is_never_imported():
    offenders = [str(p) for p in SOURCE_FILES
                 if "difflib" in imported_modules(p)]
    assert not offenders, "difflib must not be used: %s" % offenders


def test_no_subprocess_or_shell_calls():
    for path in SOURCE_FILES:
        names = imported_modules(path)
        assert "subprocess" not in names, path
        assert "pty" not in names, path
        assert "commands" not in names, path
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in (
                    "popen", "system", "execv", "execve",
                    "spawnl", "spawnv"):
                raise AssertionError(
                    "%s uses forbidden process API %s"
                    % (path, node.attr))
            if isinstance(node, ast.Name) and node.id in ("system",):
                raise AssertionError(
                    "%s references forbidden name %s" % (path, node.id))


def test_only_standard_library_imports():
    import sysconfig
    stdlib_path = pathlib.Path(sysconfig.get_paths()["stdlib"]).resolve()
    for path in SOURCE_FILES:
        for name in imported_modules(path):
            if name == "minidiff":
                continue
            module = __import__(name)
            module_file = getattr(module, "__file__", None)
            if module_file is None:
                # Built-in / frozen modules are part of the interpreter.
                continue
            resolved = pathlib.Path(module_file).resolve()
            try:
                resolved.relative_to(stdlib_path)
            except ValueError:
                raise AssertionError(
                    "%s imports non-stdlib module %r (%s)"
                    % (path, name, module_file))


def test_diff_works_with_difflib_blocked():
    """Run a round-trip in a subprocess where importing difflib fails."""
    script = (
        "import sys, builtins\n"
        "real_import = builtins.__import__\n"
        "def guarded(name, *a, **k):\n"
        "    if name == 'difflib' or name.startswith('difflib.'):\n"
        "        raise ImportError('difflib blocked')\n"
        "    return real_import(name, *a, **k)\n"
        "builtins.__import__ = guarded\n"
        "sys.path.insert(0, %r)\n"
        "from minidiff import diff_lines, unified_diff, apply_patch\n"
        "a = 'alpha\\nbeta\\ngamma\\ndelta\\n'\n"
        "b = 'alpha\\nBETA\\ngamma\\ndelta\\nend\\n'\n"
        "patch = unified_diff(a, b)\n"
        "assert apply_patch(a, patch) == b\n"
        "assert len(diff_lines(a, b)) == 6\n"
        "print('ok')\n"
    ) % str(ROOT)
    result = subprocess.run([sys.executable, "-c", script],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"
