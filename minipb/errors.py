"""minipb 的自定义异常。"""


class DecodeError(Exception):
    """解码失败。message 中带字节偏移，offset 属性也可单独取。"""

    def __init__(self, message, offset=None):
        self.offset = offset
        if offset is not None:
            message = "%s (at byte offset %d)" % (message, offset)
        super().__init__(message)


class EncodeError(ValueError):
    """编码失败（如 required 字段未赋值、数值越界、类型不对）。"""


class SchemaError(Exception):
    """schema 解析/校验失败。message 中带行号，line 属性也可单独取。"""

    def __init__(self, message, line):
        self.line = line
        super().__init__("line %d: %s" % (line, message))
