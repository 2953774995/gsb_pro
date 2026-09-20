"""datamask：客服工单敏感信息检测与脱敏工具。

核心特性：
- 自研模式语法前端（扫描、转义、递归下降解析为显式 AST），不使用 re 模块；
- 回溯型匹配引擎，带状态记忆化剪枝与步数预算，杜绝灾难性回溯；
- 内置手机号 / 身份证号 / 银行卡号 / 邮箱四类敏感信息规则与脱敏能力；
- 仅依赖 Python 标准库。
"""

from .errors import PatternError, PatternTimeoutError
from .pattern import (
    DEFAULT_MAX_STEPS,
    IGNORECASE,
    MULTILINE,
    I,
    M,
    Match,
    Pattern,
    compile,
)
from . import rules
from .rules import RULES, detect, mask

__version__ = "0.1.0"

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
    "rules",
    "RULES",
    "detect",
    "mask",
    "__version__",
]
