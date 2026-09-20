"""Built-in sensitive-data rules for customer-support tickets.

Each rule is written in datamask's own pattern syntax and pairs a
detection pattern with a mask spec: a list of (group_index, replacement)
entries.  A replacement is either a fixed string or a callable taking
the matched group text and returning the mask text.
"""

from .pattern import compile


class Rule:
    """A named detection + masking rule."""

    def __init__(self, name, pattern, mask_spec, flags=0, description=""):
        self.name = name
        self.pattern_text = pattern
        self.pattern = compile(pattern, flags)
        self.mask_spec = list(mask_spec)
        self.description = description

    def finditer(self, text):
        return self.pattern.finditer(text)

    def findall(self, text):
        return self.pattern.findall(text)

    def mask_match(self, m):
        """Build the masked replacement string for one match."""
        whole = m.group(0)
        base = m.start()
        parts = []
        cur = 0
        for gidx, repl in sorted(self.mask_spec):
            s, e = m.span(gidx)
            if s < 0:
                continue
            s -= base
            e -= base
            parts.append(whole[cur:s])
            parts.append(repl(m.group(gidx)) if callable(repl) else repl)
            cur = e
        parts.append(whole[cur:])
        return "".join(parts)

    def mask_text(self, text):
        """Return *text* with every rule match masked."""
        out = []
        last = 0
        for m in self.pattern.finditer(text):
            out.append(text[last:m.start()])
            out.append(self.mask_match(m))
            last = m.end()
        out.append(text[last:])
        return "".join(out)


RULES = {
    "phone": Rule(
        "phone",
        r"(1[3-9]\d)(\d{4})(\d{4})",
        mask_spec=[(2, "****")],
        description="中国大陆手机号：保留前 3 位与后 4 位，中间 4 位替换为 ****",
    ),
    "idcard": Rule(
        "idcard",
        r"(\d{6})(\d{8})(\d{3}[0-9Xx])",
        mask_spec=[(2, "********")],
        description="18 位身份证号：保留前 6 位与后 4 位，中间 8 位替换为 ********",
    ),
    "bankcard": Rule(
        "bankcard",
        r"(\d{4})(\d{8,11})(\d{4})",
        mask_spec=[(2, lambda s: "*" * len(s))],
        description="16-19 位银行卡号：保留前 4 位与后 4 位，中间替换为等长 *",
    ),
    "email": Rule(
        "email",
        r"([A-Za-z0-9._%+-])([A-Za-z0-9._%+-]*)(@[A-Za-z0-9.-]+\.[A-Za-z]{2,})",
        mask_spec=[(2, "***")],
        description="邮箱：本地部分保留首字符，其余替换为 ***",
    ),
}


def list_rules():
    """Return the names of all built-in rules."""
    return sorted(RULES)


def get_rule(name):
    """Look up a rule by name; raises KeyError for unknown names."""
    try:
        return RULES[name]
    except KeyError:
        raise KeyError(
            "unknown rule %r (available: %s)" % (name, ", ".join(list_rules()))
        ) from None


def mask_text(text, rule_name):
    """Mask *text* using the named rule."""
    return get_rule(rule_name).mask_text(text)
