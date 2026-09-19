"""HTML 转义工具。"""

import html


def escape(value):
    """对输出值做 HTML 转义（< > & " '）。"""
    return html.escape(str(value), quote=True)
