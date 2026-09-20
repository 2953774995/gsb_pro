"""CLI 端到端：minipb compile schema.mpb -o out.py，然后 import 生成代码跑通。"""
import importlib.util
import subprocess
import sys

SCHEMA = """\
message Person {
  required string name = 1;
  optional int32 age = 2;
  repeated string emails = 3;
  optional Address addr = 4;
}
message Address {
  required string city = 1;
  optional int32 zip = 2;
}
"""


def _run_cli(*args, cwd=None):
    return subprocess.run(
        [sys.executable, "-m", "minipb"] + list(args),
        capture_output=True, text=True, cwd=cwd)


def _import(path, name):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_cli_compile_and_roundtrip(tmp_path):
    schema_path = tmp_path / "person.mpb"
    schema_path.write_text(SCHEMA, encoding="utf-8")
    out_path = tmp_path / "person_pb.py"

    result = _run_cli("compile", str(schema_path), "-o", str(out_path))
    assert result.returncode == 0, result.stderr
    assert out_path.exists()

    mod = _import(out_path, "cli_person_pb")
    person = mod.Person(
        name="张三", age=30, emails=["a@b.com"],
        addr=mod.Address(city="上海", zip=200000))
    data = person.encode()
    back = mod.Person.decode(data)
    assert back == person
    assert back.addr.city == "上海"


def test_cli_schema_error_exit_code(tmp_path):
    bad = tmp_path / "bad.mpb"
    bad.write_text("message M {\n  optional int32 a = 1;\n  optional int32 b = 1;\n}\n",
                   encoding="utf-8")
    result = _run_cli("compile", str(bad), "-o", str(tmp_path / "out.py"))
    assert result.returncode == 1
    assert "line 3" in result.stderr
    assert "重复" in result.stderr


def test_cli_missing_file(tmp_path):
    result = _run_cli("compile", str(tmp_path / "nope.mpb"),
                      "-o", str(tmp_path / "out.py"))
    assert result.returncode == 1
    assert "nope.mpb" in result.stderr
