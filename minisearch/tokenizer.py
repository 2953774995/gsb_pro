"""分词与规范化模块。

规则：
- 英文按 [A-Za-z0-9]+ 切词，小写化，可选简化词干化；
- 中文（CJK 统一表意文字）按字符单位切分，每个汉字是一个 term；
- 可选停止词过滤（停止词仍占据位置编号，保证位置列表反映原始词序）。
"""

import re

#: 默认英文停止词表
DEFAULT_STOPWORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "of", "to", "in", "on", "at", "for", "by", "with", "as", "from",
    "and", "or", "not", "but", "if", "then", "else", "so", "than",
    "it", "its", "this", "that", "these", "those", "there", "here",
    "i", "you", "he", "she", "we", "they", "me", "him", "her", "us", "them",
    "my", "your", "his", "our", "their", "what", "which", "who", "whom",
    "do", "does", "did", "have", "has", "had", "will", "would", "can",
    "could", "shall", "should", "may", "might", "must",
})

# 英文词（ASCII 字母数字）或单个 CJK 汉字
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+|[㐀-䶿一-鿿]")


def stem(word):
    """简化版 Porter 词干化（仅处理英文小写词）。

    规则（按序应用）：
    1. 复数：sses->ss（caresses->caress），ies->i（ponies->poni），
       保留 ss 结尾，其余去掉词尾 s（cats->cat）；
    2. 后缀：去掉 ing/ed（要求剩余词干长度 >= 3），
       若结尾为双写辅音则再去掉一个（stopped->stop, running->run）。
    """
    w = word
    if len(w) <= 2:
        return w
    # 第一步：复数
    if w.endswith("sses"):
        w = w[:-2]
    elif w.endswith("ies"):
        w = w[:-3] + "i"
    elif w.endswith("ss"):
        pass
    elif w.endswith("s"):
        w = w[:-1]
    # 第二步：ed / ing
    for suffix in ("ing", "ed"):
        if w.endswith(suffix) and len(w) - len(suffix) >= 3:
            w = w[: -len(suffix)]
            if (
                len(w) >= 2
                and w[-1] == w[-2]
                and w[-1] not in "aeiou"
                and not w.endswith("ss")
            ):
                w = w[:-1]
            break
    return w


def _normalize(raw, use_stemming):
    """规范化单个原始 token，返回 term。"""
    if raw.isascii():
        term = raw.lower()
        if use_stemming:
            term = stem(term)
        return term
    return raw  # 中文单字原样返回


def tokenize(text, use_stopwords=True, use_stemming=True, stopwords=None):
    """把文本切分为 (term, position) 列表。

    position 是原始 token 序号（停止词也占位置），用于短语查询的位置验证。
    """
    if stopwords is None:
        stopwords = DEFAULT_STOPWORDS
    tokens = []
    for pos, match in enumerate(_TOKEN_RE.finditer(text)):
        raw = match.group(0)
        if (
            use_stopwords
            and raw.isascii()
            and raw.lower() in stopwords
        ):
            continue
        tokens.append((_normalize(raw, use_stemming), pos))
    return tokens


def tokenize_with_spans(text, use_stemming=True):
    """切分并保留原文字符区间，返回 (term, start, end) 列表（供摘要生成使用）。"""
    results = []
    for match in _TOKEN_RE.finditer(text):
        raw = match.group(0)
        results.append((_normalize(raw, use_stemming), match.start(), match.end()))
    return results
