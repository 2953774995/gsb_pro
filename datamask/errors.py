"""datamask 自定义异常层次。"""


class PatternError(Exception):
    """模式非法或匹配过程出错。

    属性:
        message: 错误原因描述。
        column:  出错位置在模式字符串中的列号（0 起始），无位置信息时为 None。
        pattern: 出错的模式原文（可能为 None）。
    """

    def __init__(self, message, column=None, pattern=None):
        self.message = message
        self.column = column
        self.pattern = pattern
        if column is not None:
            super().__init__("%s (column %d)" % (message, column))
        else:
            super().__init__(message)

    def __repr__(self):
        return "PatternError(%r, column=%r)" % (self.message, self.column)


class PatternTimeoutError(PatternError):
    """单次匹配超过步数上限。"""

    def __init__(self, steps, limit):
        self.steps = steps
        self.limit = limit
        super().__init__(
            "match aborted: step budget exceeded (%d steps, limit %d)"
            % (steps, limit)
        )
