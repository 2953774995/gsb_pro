"""灾难性回溯防护测试：经典退化用例必须快速失败或安全终止。"""

import time

import pytest

from datamask import PatternError, PatternTimeoutError, compile

# 经典指数级退化模式与输入
CATASTROPHIC = [
    ("(a+)+$", "a" * 5000 + "b"),
    ("(a|a)*b", "a" * 5000),
    ("(a*)*b", "a" * 5000),
    ("(.*)*b", "a" * 2000),
    ("(x+x+)+y", "x" * 5000),
]


@pytest.mark.parametrize("pattern,text", CATASTROPHIC)
def test_catastrophic_backtracking_terminates_fast(pattern, text):
    """默认步数上限下，退化用例必须在受限时间内安全终止（不卡死）。"""
    start = time.monotonic()
    result = compile(pattern).search(text)
    elapsed = time.monotonic() - start
    assert result is None
    assert elapsed < 10.0, "took %.2fs" % elapsed


def test_step_budget_exceeded_raises():
    """步数预算超限时抛 PatternTimeoutError，且快速失败。"""
    p = compile("(a+)+$", max_steps=1000)
    start = time.monotonic()
    with pytest.raises(PatternTimeoutError) as excinfo:
        p.search("a" * 10000 + "b")
    assert time.monotonic() - start < 5.0
    err = excinfo.value
    assert err.limit == 1000
    assert "step budget" in str(err)


def test_timeout_is_pattern_error_subclass():
    assert issubclass(PatternTimeoutError, PatternError)
    with pytest.raises(PatternError):
        compile("a+", max_steps=1).search("aaaaaaaaaa")


def test_per_call_budget_override():
    p = compile("a+")
    assert p.search("aaaa") is not None
    with pytest.raises(PatternTimeoutError):
        p.search("aaaa", max_steps=1)


def test_large_input_normal_pattern():
    """正常模式在大输入上应高效完成。"""
    text = "工单内容 " * 20000 + "13812345678"
    start = time.monotonic()
    m = compile(r"1[3-9]\d{9}").search(text)
    assert m is not None
    assert time.monotonic() - start < 10.0


def test_deep_repeat_expansion_guard():
    """过度展开的模式必须被程序大小上限拦截，而不是耗尽内存。"""
    with pytest.raises(PatternError) as excinfo:
        compile("(?:a{65535}){65535}")
    assert "too large" in str(excinfo.value)
