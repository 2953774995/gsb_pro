"""命中摘要生成：以第一个命中词为中心截取共 width 字符的窗口。"""

from .tokenizer import tokenize_with_spans

DEFAULT_WIDTH = 80


def make_snippet(text, terms, width=DEFAULT_WIDTH, use_stemming=True):
    """生成命中摘要。

    在原文中找到第一个命中 term 的位置，以其为中心截取前后共 width 字符，
    截断处以 ... 标示。无命中时返回开头 width 字符。
    """
    if not text:
        return ""
    hit = None
    if terms:
        for term, start, end in tokenize_with_spans(text, use_stemming=use_stemming):
            if term in terms:
                hit = (start, end)
                break
    if hit is None:
        snippet = text[:width]
        return snippet + ("..." if len(text) > width else "")
    start, end = hit
    # 以命中词为中心确定窗口
    center = (start + end) // 2
    win_start = max(0, center - width // 2)
    win_end = min(len(text), win_start + width)
    win_start = max(0, win_end - width)
    snippet = text[win_start:win_end]
    prefix = "..." if win_start > 0 else ""
    suffix = "..." if win_end < len(text) else ""
    return prefix + snippet + suffix
