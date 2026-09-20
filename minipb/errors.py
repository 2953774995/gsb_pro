"""minipb 的自定义异常。"""


class MiniPBError(Exception):
    """minipb 所有异常的基类。"""


class SchemaError(MiniPBError):
    """schema 解析错误，带行号。"""

    def __init__(self, message, line=None):
        self.message = message
        self.line = line
        if line is not None:
            super().__init__("line %d: %s" % (line, message))
        else:
            super().__init__(message)


class DecodeError(MiniPBError):
    """二进制解码错误，带字节偏移。"""

    def __init__(self, message, offset):
        self.message = message
        self.offset = offset
        super().__init__("decode error at offset %d: %s" % (offset, message))


class EncodeError(MiniPBError):
    """编码错误（required 缺失、数值越界、类型不对等）。"""
