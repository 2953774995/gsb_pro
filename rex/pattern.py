"""Public Pattern / Match API for the rex engine."""

from .errors import RegexError, RegexTimeoutError
from .engine import compile_tree, run_vm
from .parser import parse
from . import flags as _flags

DEFAULT_MAX_STEPS = 100_000_000

_VALID_FLAGS = _flags.IGNORECASE | _flags.MULTILINE


def compile(pattern, flags=0, max_steps=DEFAULT_MAX_STEPS):
    """Compile a regular expression string into a :class:`Pattern`."""
    if isinstance(pattern, Pattern):
        return pattern
    if not isinstance(pattern, str):
        raise TypeError("pattern must be a string")
    if flags & ~_VALID_FLAGS:
        raise ValueError("unknown flag value: %r" % (flags,))
    tree, meta = parse(pattern)
    program = compile_tree(tree, meta, flags)
    return Pattern(pattern, flags, program, max_steps)


class Match(object):
    """Result of a successful match."""

    __slots__ = ("_pattern", "_string", "_start", "_end", "_caps", "_groups")

    def __init__(self, pattern_obj, string, start, end, caps, groups):
        self._pattern = pattern_obj
        self._string = string
        self._start = start
        self._end = end
        self._caps = caps
        self._groups = groups

    # -- accessors ----------------------------------------------------------

    def _resolve(self, key):
        if key == 0 or key is None:
            return self._start, self._end
        if isinstance(key, str):
            slot = self._pattern._name_slots.get(key)
            if slot is None:
                raise IndexError("no such group: %r" % key)
        else:
            slot = self._pattern._num_slots.get(key)
            if slot is None:
                raise IndexError("no such group: %d" % key)
        s, e = self._caps[2 * slot], self._caps[2 * slot + 1]
        return s, e

    def group(self, *keys):
        if not keys:
            return self._string[self._start : self._end]
        if len(keys) == 1:
            return self._one(keys[0])
        return tuple(self._one(k) for k in keys)

    def _one(self, key):
        s, e = self._resolve(key)
        if s is None:
            return None
        return self._string[s:e]

    def groups(self, default=None):
        out = []
        for slot in self._groups:
            s, e = self._caps[2 * slot], self._caps[2 * slot + 1]
            out.append(default if s is None else self._string[s:e])
        return tuple(out)

    def groupdict(self, default=None):
        out = {}
        for name, slot in self._pattern._name_slots.items():
            s, e = self._caps[2 * slot], self._caps[2 * slot + 1]
            out[name] = default if s is None else self._string[s:e]
        return out

    def start(self, key=0):
        value = self._resolve(key)[0]
        return -1 if value is None else value

    def end(self, key=0):
        value = self._resolve(key)[1]
        return -1 if value is None else value

    def span(self, key=0):
        s, e = self._resolve(key)
        return (-1, -1) if s is None else (s, e)

    @property
    def string(self):
        return self._string

    @property
    def re(self):
        return self._pattern

    @property
    def pos(self):
        return self._start

    @property
    def endpos(self):
        return self._end

    def __getitem__(self, key):
        return self._one(key)

    def __repr__(self):
        return "<rex.Match object; span=(%d, %d), match=%r>" % (
            self._start,
            self._end,
            self._string[self._start : self._end],
        )


class Pattern(object):
    """A compiled regular expression."""

    def __init__(self, pattern_string, flags, program, max_steps):
        self.pattern = pattern_string
        self.flags = flags
        self._program = program
        self.max_steps = max_steps

        # Slots are assigned in opening-parenthesis order; numeric indices
        # only count unnamed captures.
        self._name_slots = dict(program.names)
        self._num_slots = {}
        num = 0
        for slot in range(program.group_count):
            if slot in program.names.values():
                continue
            num += 1
            self._num_slots[num] = slot
        # All captures in opening-paren order for groups().
        self._group_slots = tuple(range(program.group_count))
        self.groups_count = num
        self.groupindex = {
            name: idx + 1
            for idx, name in enumerate(
                n for n, s in sorted(program.names.items(), key=lambda kv: kv[1])
            )
        }

    def __repr__(self):
        return "rex.compile(%r, %d)" % (self.pattern, self.flags)

    # -- core execution -----------------------------------------------------

    def _budget(self):
        return [self.max_steps, self.max_steps]

    def _make_match(self, string, start, end, caps):
        return Match(self, string, start, end, caps, self._group_slots)

    def match(self, string, pos=0, endpos=None):
        if not isinstance(string, str):
            raise TypeError("string must be a str")
        if pos < 0:
            pos = 0
        if pos > len(string):
            pos = len(string)
        budget = self._budget()
        result = run_vm(self._program, string, pos, True, budget, must_end=endpos)
        if result is None:
            return None
        return self._make_match(string, *result)

    def fullmatch(self, string, pos=0, endpos=None):
        if not isinstance(string, str):
            raise TypeError("string must be a str")
        if pos < 0:
            pos = 0
        if pos > len(string):
            pos = len(string)
        stop = len(string) if endpos is None else min(endpos, len(string))
        budget = self._budget()
        result = run_vm(self._program, string, pos, True, budget, must_end=stop)
        if result is None:
            return None
        return self._make_match(string, *result)

    def search(self, string, pos=0, endpos=None):
        if not isinstance(string, str):
            raise TypeError("string must be a str")
        n = len(string)
        if pos < 0:
            pos = 0
        if pos > n:
            pos = n
        limit = n if endpos is None else min(endpos, n)
        # The VM itself walks start positions; we enforce endpos by slicing
        # the view the VM operates on only when it would walk past limit.
        budget = self._budget()
        result = run_vm(
            self._program, string, pos, False, budget, scan_limit=limit
        )
        if result is None:
            return None
        return self._make_match(string, *result)

    def finditer(self, string, pos=0, endpos=None):
        if not isinstance(string, str):
            raise TypeError("string must be a str")
        n = len(string)
        if pos < 0:
            pos = 0
        if pos > n:
            pos = n
        limit = n if endpos is None else min(endpos, n)

        def generate():
            from .engine import attempt_matches

            i = pos
            while i <= limit:
                budget = self._budget()
                gen = attempt_matches(self._program, string, i, limit, budget)
                try:
                    start, end, caps = next(gen)
                except StopIteration:
                    i += 1
                    continue
                if start != end:
                    gen.close()
                    yield self._make_match(string, start, end, caps)
                    i = end
                    continue

                # Zero-length match: yield it, then resume the same attempt
                # to see whether a lazy quantifier can grow at this position.
                yield self._make_match(string, start, end, caps)
                growth = None
                for candidate in gen:
                    if candidate[1] != candidate[0]:
                        growth = candidate
                        break
                gen.close()
                if growth is None:
                    i = end + 1
                else:
                    gstart, gend, gcaps = growth
                    yield self._make_match(string, gstart, gend, gcaps)
                    i = gend
            return

        return generate()

    def findall(self, string, pos=0, endpos=None):
        results = []
        group_count = self._program.group_count
        for m in self.finditer(string, pos, endpos):
            if group_count == 0:
                results.append(m.group())
            elif group_count == 1:
                # In findall a non-participating group is reported as ''.
                value = m.groups(default="")[0]
                results.append(value)
            else:
                results.append(m.groups(default=""))
        return results

    def split(self, string, maxsplit=0):
        parts = []
        cursor = 0
        count = 0
        for m in self.finditer(string):
            parts.append(string[cursor : m.start()])
            parts.extend(m.groups())
            cursor = m.end()
            count += 1
            if maxsplit and count >= maxsplit:
                break
        parts.append(string[cursor:])
        return parts

    def sub(self, repl, string, count=0):
        if callable(repl):
            render = repl
        else:
            def render(m, template=repl):
                return _expand_template(template, m)
        out = []
        cursor = 0
        n = 0
        for m in self.finditer(string):
            out.append(string[cursor : m.start()])
            out.append(render(m))
            cursor = m.end()
            n += 1
            if count and n >= count:
                break
        out.append(string[cursor:])
        return "".join(out)


def _expand_template(template, match):
    out = []
    i = 0
    n = len(template)
    while i < n:
        ch = template[i]
        if ch != "\\":
            out.append(ch)
            i += 1
            continue
        i += 1
        if i >= n:
            raise RegexError("bad escape in replacement template", i - 1)
        marker = template[i]
        if marker.isdigit():
            value = match.group(int(marker))
            out.append("" if value is None else value)
            i += 1
        elif marker == "g":
            if i + 1 < n and template[i + 1] == "<":
                close = template.find(">", i + 2)
                if close == -1:
                    raise RegexError("missing '>' in replacement group reference", i)
                name = template[i + 2 : close]
                value = match.group(name)
                out.append("" if value is None else value)
                i = close + 1
            else:
                raise RegexError("bad escape in replacement template", i)
        else:
            out.append(marker)
            i += 1
    return "".join(out)
