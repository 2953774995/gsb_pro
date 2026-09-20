"""字符扫描与转义表。

本模块集中定义模式语法中所有转义序列的含义，供解析器在
"分组外" 与 "字符类内" 两种上下文复用，保证语义一致、便于审计。
"""

# 简单单字符转义：\n \t \r
SIMPLE_ESCAPES = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
}

# 字符类缩写（分组外与字符类内均可使用）
CLASS_CODES = frozenset("dDwWsS")

# 十六进制转义前缀 -> 需要的十六进制位数
HEX_ESCAPES = {
    "x": 2,   # \xHH
    "u": 4,   # \uXXXX
}

HEX_DIGITS = frozenset("0123456789abcdefABCDEF")


def is_class_code(ch):
    return ch in CLASS_CODES


def is_word_char(ch):
    """\\w 的字符判定：字母、数字、下划线（含 Unicode 字母数字）。"""
    return ch == "_" or ch.isalnum()


def is_space_char(ch):
    """\\s 的字符判定。"""
    return ch in " \t\n\r\f\v"


def class_code_matches(code, ch):
    """判断字符 ch 是否匹配字符类缩写 code（d/D/w/W/s/S）。"""
    if code == "d":
        return "0" <= ch <= "9"
    if code == "D":
        return not ("0" <= ch <= "9")
    if code == "w":
        return is_word_char(ch)
    if code == "W":
        return not is_word_char(ch)
    if code == "s":
        return is_space_char(ch)
    if code == "S":
        return not is_space_char(ch)
    raise AssertionError("unknown class code: %r" % code)
