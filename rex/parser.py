"""Recursive-descent parser: pattern text -> AST.

Grammar (EBNF)::

    regex      := alternate
    alternate  := concat ("|" concat)*
    concat     := repeat*
    repeat     := atom quantifier? "?"?        (trailing ? = lazy)
    quantifier := "*" | "+" | "?" | "{m}" | "{m,}" | "{m,n}"
    atom       := literal | "." | "^" | "$" | class_escape
                | char_class | group
    group      := "(" regex ")" | "(?:" regex ")" | "(?P<name>" regex ")"
    char_class := "[" "^"? class_item* "]"
"""

from . import ast
from .errors import RegexError
from .scanner import Scanner, Token

MAX_REPEAT = 65535

_GROUP_INDEX_LIMIT = 99


class Parser:
    def __init__(self, pattern):
        self.scanner = Scanner(pattern)
        self.group_count = 0
        self.group_names = {}
        self.named_count = 0

    # -- helpers ---------------------------------------------------------

    def error(self, message, pos=None):
        self.scanner.error(message, pos)

    def peek(self):
        return self.scanner.peek()

    # -- entry point -----------------------------------------------------

    def parse(self):
        node = self.parse_alternate()
        if not self.scanner.at_end():
            tok = self.scanner.read_token()
            if tok.kind == "meta" and tok.value == ")":
                self.error("unbalanced closing parenthesis", tok.pos)
            self.error("unexpected %r" % tok.value, tok.pos)
        return node

    # -- grammar rules ---------------------------------------------------

    def parse_alternate(self):
        branches = [self.parse_concat()]
        while True:
            save = self.scanner.pos
            if self.peek() != "|":
                break
            tok = self.scanner.read_token()
            if tok.kind != "meta" or tok.value != "|":
                self.scanner.pos = save
                break
            branches.append(self.parse_concat())
        if len(branches) == 1:
            return branches[0]
        return ast.Alternate(branches)

    def parse_concat(self):
        children = []
        while not self.scanner.at_end():
            ch = self.peek()
            if ch in ")|":
                break
            children.append(self.parse_repeat())
        if not children:
            return ast.Concat([])
        if len(children) == 1:
            return children[0]
        return ast.Concat(children)

    def parse_repeat(self):
        atom = self.parse_atom()
        tok = self._peek_token()
        if tok is None:
            return atom
        if tok.kind == "meta" and tok.value in "*+?":
            self.scanner.read_token()
            lo, hi = {"*": (0, None), "+": (1, None), "?": (0, 1)}[tok.value]
            return self._make_repeat(atom, lo, hi, tok.pos)
        if tok.kind == "meta" and tok.value == "{":
            bounds = self._try_parse_brace_quantifier()
            if bounds is None:
                return atom  # literal "{"
            lo, hi, _pos = bounds
            return self._make_repeat(atom, lo, hi, _pos)
        return atom

    def _make_repeat(self, atom, lo, hi, pos):
        if isinstance(atom, ast.Anchor):
            self.error("nothing to repeat: quantifier cannot follow an anchor", pos)
        greedy = True
        if self.peek() == "?":
            self.scanner.read_token()
            greedy = False
        return ast.Repeat(atom, lo, hi, greedy)

    def _try_parse_brace_quantifier(self):
        """Parse ``{m}`` / ``{m,}`` / ``{m,n}``; return None if it is not a
        valid quantifier (then ``{`` is treated as a literal)."""
        save = self.scanner.pos
        start = self.scanner.pos
        self.scanner.read_token()  # consume "{"
        lo_digits = self._read_digits()
        if lo_digits is None:
            self.scanner.pos = save
            return None
        hi = lo = int(lo_digits)
        if self.peek() == ",":
            self.scanner.advance()
            hi_digits = self._read_digits()
            hi = int(hi_digits) if hi_digits is not None else None
        if self.peek() != "}":
            self.error("malformed quantifier: expected '}'", start)
        self.scanner.advance()
        if lo > MAX_REPEAT or (hi is not None and hi > MAX_REPEAT):
            self.error(
                "repeat count out of range (max %d)" % MAX_REPEAT, start
            )
        if hi is not None and lo > hi:
            self.error(
                "quantifier bounds out of order: {%d,%d}" % (lo, hi), start
            )
        return lo, hi, start

    def _read_digits(self):
        start = self.scanner.pos
        while not self.scanner.at_end() and self.scanner.peek().isdigit():
            self.scanner.advance()
        if self.scanner.pos == start:
            return None
        return self.scanner.pattern[start:self.scanner.pos]

    def parse_atom(self):
        tok = self.scanner.read_token()
        if tok.kind == "literal":
            return ast.Literal(tok.value)
        if tok.kind == "class_escape":
            return ast.ClassEscape(tok.value)
        if tok.kind == "backref":
            self.error(
                "backreferences (\\%s) are not supported" % tok.value, tok.pos
            )
        # meta characters
        ch = tok.value
        if ch == ".":
            return ast.Dot()
        if ch == "^":
            return ast.Anchor("start")
        if ch == "$":
            return ast.Anchor("end")
        if ch == "[":
            return self.parse_char_class(tok.pos)
        if ch == "(":
            return self.parse_group(tok.pos)
        if ch == ")":
            self.error("unbalanced closing parenthesis", tok.pos)
        if ch in "*+?":
            self.error("nothing to repeat before '%s'" % ch, tok.pos)
        if ch == "{":
            # A "{" that starts a valid quantifier here has no preceding
            # atom; otherwise it is a plain literal.
            if self._looks_like_quantifier(tok.pos):
                self.error("nothing to repeat before '{'", tok.pos)
            return ast.Literal("{")
        if ch == "}":
            return ast.Literal("}")
        self.error("unexpected '%s'" % ch, tok.pos)

    def _looks_like_quantifier(self, brace_pos):
        save = self.scanner.pos
        self.scanner.pos = brace_pos
        result = self._try_parse_brace_quantifier() is not None
        self.scanner.pos = save
        return result

    # -- groups ----------------------------------------------------------

    def parse_group(self, start):
        index = None
        name = None
        if self.scanner.peek() == "?":
            self.scanner.advance()
            nxt = self.scanner.advance() if not self.scanner.at_end() else None
            if nxt == ":":
                pass  # non-capturing group
            elif nxt == "P":
                name = self._parse_group_name(start)
                # Named groups capture but do not consume a numeric
                # index; their capture slot is assigned after parsing.
                self.named_count += 1
            else:
                self.error(
                    "unsupported group syntax '(?%s'" % (nxt or ""), start
                )
        else:
            index = self._next_group_index(start)
        child = self.parse_alternate()
        if self.scanner.at_end():
            self.error("unterminated group: missing ')'", start)
        tok = self.scanner.read_token()
        if tok.kind != "meta" or tok.value != ")":
            self.error("unterminated group: missing ')'", start)
        return ast.Group(child, index, name)

    def _next_group_index(self, pos):
        self.group_count += 1
        if self.group_count > _GROUP_INDEX_LIMIT:
            self.error("too many capture groups (max %d)" % _GROUP_INDEX_LIMIT, pos)
        return self.group_count

    def _parse_group_name(self, group_start):
        if self.scanner.peek() != "<":
            self.error("expected '<' after '?P'", group_start)
        self.scanner.advance()
        start = self.scanner.pos
        while not self.scanner.at_end() and self.scanner.peek() != ">":
            self.scanner.advance()
        if self.scanner.at_end():
            self.error("unterminated group name", start)
        name = self.scanner.pattern[start:self.scanner.pos]
        self.scanner.advance()  # consume ">"
        if not name:
            self.error("empty group name", start)
        if not (name[0].isalpha() or name[0] == "_") or not all(
            c.isalnum() or c == "_" for c in name
        ):
            self.error("invalid group name %r" % name, start)
        if name in self.group_names:
            self.error("duplicate group name %r" % name, start)
        self.group_names[name] = None  # index filled in by caller order
        return name

    # -- character classes -----------------------------------------------

    def parse_char_class(self, class_start):
        negated = False
        if self.scanner.peek() == "^":
            self.scanner.advance()
            negated = True
        items = []
        first = True
        while True:
            if self.scanner.at_end():
                self.error("unterminated character class", class_start)
            tok = self.scanner.read_class_token()
            if tok.kind == "meta" and tok.value == "]" and not first:
                break
            first = False
            item = self._class_item_from_token(tok)
            # Possible range: item "-" item
            if (
                item[0] == "lit"
                and self.scanner.peek() == "-"
                and self._class_has_char_after_dash()
            ):
                self.scanner.advance()  # consume "-"
                end_tok = self.scanner.read_class_token()
                end_item = self._class_item_from_token(end_tok)
                if end_item[0] != "lit":
                    self.error(
                        "character class range cannot end with \\%s"
                        % end_item[1],
                        end_tok.pos,
                    )
                lo, hi = item[1], end_item[1]
                if ord(lo) > ord(hi):
                    self.error(
                        "character class range out of order: %s-%s" % (lo, hi),
                        tok.pos,
                    )
                items.append(("range", lo, hi))
            else:
                items.append(item)
        if not items:
            self.error("empty character class", class_start)
        return ast.CharClass(items, negated)

    def _class_has_char_after_dash(self):
        """True when ``-`` (at cursor) is followed by a real class item,
        i.e. the next char is not the closing ``]``."""
        pos = self.scanner.pos
        if self.scanner.pattern[pos] != "-":
            return False
        if pos + 1 >= self.scanner.length:
            return False
        return self.scanner.pattern[pos + 1] != "]"

    def _class_item_from_token(self, tok):
        if tok.kind == "literal":
            return ("lit", tok.value)
        if tok.kind == "class_escape":
            return ("class", tok.value)
        if tok.kind == "backref":
            self.error(
                "backreferences (\\%s) are not supported" % tok.value, tok.pos
            )
        # meta tokens inside a class
        if tok.value == "-":
            return ("lit", "-")
        if tok.value == "^":
            return ("lit", "^")
        if tok.value == "]":
            # Only reachable as the very first item (e.g. "[]a]").
            return ("lit", "]")
        self.error("unexpected '%s' in character class" % tok.value, tok.pos)

    # -- token lookahead --------------------------------------------------

    def _peek_token(self):
        if self.scanner.at_end():
            return None
        save = self.scanner.pos
        tok = self.scanner.read_token()
        self.scanner.pos = save
        return tok


def parse(pattern):
    """Parse *pattern*.

    Returns ``(ast, group_count, group_names, slot_count)`` where
    ``group_count`` is the number of *numbered* capture groups,
    ``group_names`` maps each named group to its capture slot, and
    ``slot_count`` is the total number of capture slots (numbered +
    named).  Named groups do not consume numeric indices; their slots
    live after the numbered ones.
    """
    parser = Parser(pattern)
    node = parser.parse()
    names = {}
    next_named_slot = [parser.group_count + 1]

    def assign(node):
        if isinstance(node, ast.Group):
            if node.name is not None:
                node.index = next_named_slot[0]
                names[node.name] = node.index
                next_named_slot[0] += 1
            assign(node.child)
        elif isinstance(node, ast.Concat):
            for child in node.children:
                assign(child)
        elif isinstance(node, ast.Alternate):
            for branch in node.branches:
                assign(branch)
        elif isinstance(node, ast.Repeat):
            assign(node.child)

    assign(node)
    slot_count = parser.group_count + parser.named_count
    return node, parser.group_count, names, slot_count
