"""datamask: 客服工单敏感信息检测与脱敏工具。

自研模式匹配引擎（纯标准库，不使用 re 模块）：
扫描 -> 解析(AST) -> 编译(指令序列) -> 回溯 VM 执行。
"""

from .errors import PatternError, PatternTimeoutError
from .options import (
    DEFAULT_MAX_STEPS,
    IGNORECASE,
    MULTILINE,
    I,
    M,
)
from .pattern import Match, Pattern, compile
from .rules import get_rule, list_rules, mask_text

__version__ = "1.0.0"

__all__ = [
    "compile",
    "Pattern",
    "Match",
    "PatternError",
    "PatternTimeoutError",
    "IGNORECASE",
    "MULTILINE",
    "I",
    "M",
    "DEFAULT_MAX_STEPS",
    "get_rule",
    "list_rules",
    "mask_text",
    "__version__",
]
