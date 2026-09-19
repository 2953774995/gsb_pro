"""Split template source into text / variable / statement tokens."""

import re
from collections import namedtuple

from .errors import TplError

Token = namedtuple("Token", ["kind", "value", "line"])

# Matches {{ ... }}, {% ... %} and {# ... #} (non-greedy, may span lines).
_TOKEN_RE = re.compile(r"({{.*?}}|{%.*?%}|{#.*?#})", re.DOTALL)

_MARKERS = ("{{", "{%", "{#")


def tokenize(source, template=None):
    """Return a list of Tokens. Comments are dropped.

    Raises TplError on unclosed tags.
    """
    tokens = []
    pos = 0
    line = 1
    for match in _TOKEN_RE.finditer(source):
        start = match.start()
        if start > pos:
            text = source[pos:start]
            tokens.append(Token("text", text, line))
            line += text.count("\n")
        raw = match.group(0)
        if raw.startswith("{#"):
            pass  # comment: dropped entirely
        elif raw.startswith("{{"):
            tokens.append(Token("var", raw[2:-2].strip(), line))
        else:
            tokens.append(Token("tag", raw[2:-2].strip(), line))
        line += raw.count("\n")
        pos = match.end()
    if pos < len(source):
        tokens.append(Token("text", source[pos:], line))

    # Anything that looks like an opening delimiter left in a text token
    # means a tag was never closed.
    for tok in tokens:
        if tok.kind != "text":
            continue
        for marker in _MARKERS:
            idx = tok.value.find(marker)
            if idx != -1:
                bad_line = tok.line + tok.value[:idx].count("\n")
                raise TplError(
                    "unclosed tag: %r is never closed" % marker,
                    line=bad_line,
                    template=template,
                )
    return tokens
