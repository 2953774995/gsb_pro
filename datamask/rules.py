"""内置敏感信息规则包。

四类规则均用 datamask 自身的模式语法书写（不依赖 re）：
- mobile:   中国大陆手机号，保留前 3 位与后 4 位，中间 4 位替换为 ****
- idcard:   18 位身份证号，保留前 6 位地址码与后 4 位，出生日期段替换为 ********
- bankcard: 16-19 位银行卡号，保留前 4 位与后 4 位，中间按长度替换为 *
- email:    邮箱，本地部分仅保留首字符，其余替换为 ***

脱敏规则按规则名配置：masks 字典把捕获组编号映射为替换策略——
字符串表示直接替换为该字符串；None 表示替换为等长的 '*'。
"""

from .errors import PatternError
from .pattern import compile as _compile

# 替换策略：None 表示按原长度替换为 '*'
STAR_PER_CHAR = None


class Rule(object):
    """一条敏感信息检测/脱敏规则。"""

    def __init__(self, name, pattern, masks, description):
        self.name = name
        self.source = pattern
        self.masks = dict(masks)
        self.description = description
        self._pattern = _compile(pattern)

    @property
    def pattern(self):
        return self._pattern

    def finditer(self, text):
        return self._pattern.finditer(text)

    def search(self, text):
        return self._pattern.search(text)

    def mask(self, text):
        return mask(text, [self.name])

    def __repr__(self):
        return "Rule(%r, pattern=%r)" % (self.name, self.source)


RULES = {}


def _register(name, pattern, masks, description):
    RULES[name] = Rule(name, pattern, masks, description)


_register(
    "mobile",
    r"(1[3-9]\d)(\d{4})(\d{4})",
    {2: "****"},
    "中国大陆手机号：保留前 3 位与后 4 位，中间替换为 ****",
)
_register(
    "idcard",
    r"(\d{6})(\d{8})(\d{3}[\dXx])",
    {2: "********"},
    "18 位身份证号：保留前 6 位与后 4 位，出生日期段替换为 ********",
)
_register(
    "bankcard",
    r"(\d{4})(\d{8,11})(\d{4})",
    {2: STAR_PER_CHAR},
    "16-19 位银行卡号：保留前 4 位与后 4 位，中间按长度替换为 *",
)
_register(
    "email",
    r"([A-Za-z0-9._%+-])([A-Za-z0-9._%+-]*)@([A-Za-z0-9.-]+\.[A-Za-z]{2,})",
    {2: "***"},
    "邮箱：本地部分仅保留首字符，其余替换为 ***",
)


def get_rule(name):
    try:
        return RULES[name]
    except KeyError:
        raise PatternError(
            "unknown rule %r (available: %s)"
            % (name, ", ".join(sorted(RULES))))


def _resolve_names(rule_names):
    if rule_names is None or rule_names == "all":
        return list(RULES)
    if isinstance(rule_names, str):
        rule_names = [rule_names]
    names = list(rule_names)
    for name in names:
        get_rule(name)  # 提前校验规则名
    return names


def detect(text, rule_names=None):
    """检测文本中的敏感信息，返回命中字典列表（按出现位置排序）。"""
    hits = []
    for name in _resolve_names(rule_names):
        rule = RULES[name]
        for m in rule.finditer(text):
            hits.append({
                "rule": name,
                "span": m.span(),
                "text": m.group(0),
                "groups": m.groups(),
            })
    hits.sort(key=lambda h: h["span"])
    return hits


def mask(text, rule_names=None):
    """按规则对文本脱敏：把规则配置的捕获组替换为 '*'。

    rule_names 为规则名、规则名列表、'all' 或 None（全部规则）。
    多条规则命中重叠区间时，同一起点取最长命中；长度相同则先注册
    的规则优先认领整个命中区间，其余规则对该区间的命中被忽略。
    """
    # 收集全部规则的候选命中，按 (起点升序, 长度降序, 规则注册顺序) 排序，
    # 依次认领不重叠区间：同一起点取最长命中，长度相同取先注册的规则。
    candidates = []
    for order, name in enumerate(_resolve_names(rule_names)):
        rule = RULES[name]
        for m in rule.finditer(text):
            m_start, m_end = m.span()
            candidates.append((m_start, -(m_end - m_start), order, rule, m))
    candidates.sort(key=lambda c: (c[0], c[1], c[2]))
    claimed = []      # 已被认领的命中区间 (start, end)
    replacements = []  # 待应用的替换 (start, end, replacement)
    for m_start, neg_len, _order, rule, m in candidates:
        m_end = m_start - neg_len
        if any(s < m_end and m_start < e for s, e in claimed):
            continue  # 与更高优先级命中重叠，跳过
        claimed.append((m_start, m_end))
        for group_index, spec in rule.masks.items():
            start, end = m.span(group_index)
            if start < 0:
                continue
            if spec is None:
                spec_text = "*" * (end - start)
            else:
                spec_text = spec
            replacements.append((start, end, spec_text))
    replacements.sort(key=lambda r: (r[0], r[1]))
    out = []
    cursor = 0
    for start, end, spec_text in replacements:
        if start < cursor:
            continue  # 与已应用的替换重叠，跳过
        out.append(text[cursor:start])
        out.append(spec_text)
        cursor = end
    out.append(text[cursor:])
    return "".join(out)
