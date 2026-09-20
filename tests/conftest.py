import importlib.util
import sys

import pytest

from minipb.cli import main as cli_main


@pytest.fixture
def compile_schema(tmp_path):
    """给定 .mpb 文本，走 CLI 编译并动态加载生成的模块。"""

    def _compile(text, name="gen"):
        mpb = tmp_path / ("%s.mpb" % name)
        mpb.write_text(text, encoding="utf-8")
        out = tmp_path / ("%s_pb.py" % name)
        assert cli_main(["compile", str(mpb), "-o", str(out)]) == 0
        spec = importlib.util.spec_from_file_location(name, str(out))
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module

    return _compile
