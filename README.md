# rex — a mini regular expression engine

`rex` is a small but complete regular expression engine written from scratch
using **only the Python standard library**.  It has its own character scanner,
recursive-descent parser, explicit AST and a backtracking virtual machine —
the stdlib `re` module is never used for any matching logic.

## Architecture

```
pattern string
     │
     ▼
rex/scanner.py      character scanning + escape table (\d \xHH \uHHHH ...)
     │
     ▼
rex/parser.py       recursive-descent parser  ──►  rex/ast_nodes.py (explicit AST)
     │
     ▼
rex/engine.py       AST → flat byte-code, executed by a backtracking VM
     │                (explicit choice stack + per-attempt step budget)
     ▼
rex/pattern.py      compile(), Pattern, Match (search/match/fullmatch/
                     findall/finditer, groups, named captures)
     │
     ▼
rex/cli.py          rex-cli command line front end
```

### Why a VM instead of recursive function calls

The matcher compiles the AST to a small instruction set and runs it on an
interpreter with an *explicit* Python-list choice stack.  This keeps matching
immune to Python recursion-depth limits on long inputs and makes the global
step budget a single cheap counter that cannot be bypassed by recursion.

Instructions:

| instruction | meaning |
| --- | --- |
| `("char", ch)` | consume one character equal to `ch` (case-aware) |
| `("any",)` | consume any character except `\n` |
| `("class", ClassMatcher)` | consume one character accepted by a `[...]` class |
| `("anchor", kind)` | zero-width `^` / `$` assertion |
| `("split", a, b)` | continue at `a`, remember `b` as an alternative |
| `("jmp", target)` | unconditional jump |
| `("gstart", slot)` / `("gend", slot)` | record a capture start/end |
| `("match",)` | report success |

Quantifiers compile to `split`/`jmp` loops (`*`, `+`, `?`, `{m}`, `{m,}`,
`{m,n}`), with greedy and lazy (`*?`, `+?`, `??`, `{m,n}?`) choosing opposite
split targets.

## Supported syntax

- Literal characters, anchors `^` `$`, wildcard `.` (never matches `\n`)
- Character classes `[abc]`, `[^abc]`, `[a-z0-9]`
  - ranges with `-`, negation with leading `^`, escapes inside classes
  - `[]` and `[^]` are rejected as unterminated classes; `[]]` = literal `]`,
    `[-a]` / `[a-]` keep `-` literal at the edges
- Escapes: `\d \D \w \W \s \S \n \t \r \\ \. \* \+ \? \( \) \[ \] \|`
  plus the hexadecimal escapes `\xHH` and `\uHHHH`
- Quantifiers: `* + ? {m} {m,} {m,n}`, all with lazy `?` suffixes
- Groups: capturing `(...)`, non-capturing `(?:...)`, named `(?P<name>...)`
- Alternation `|` (left-to-right preference, lowest precedence)
- Flags: `IgnoreCase` and `Multiline`

### Capture numbering

Capturing groups are ordered by their **opening parenthesis**.  Named groups
do **not** consume a numeric id — `group(1)` refers to the first *unnamed*
group; named groups are accessed via `group("name")` / `groupdict()`.
`groups()` returns every capture (named and unnamed) in opening-paren order.

### Semantics

- Greedy-first backtracking, lazy quantifiers available, `*` may match zero
- Empty matches are allowed; `finditer`/`findall` implement the classic
  adjacent-empty-match advancement rules (including lazy zero-length growth)
- `Multiline`: `^`/`$` match every line start/end; `$` matches immediately
  before a `\n`.  Without it `$` matches text end or the single trailing
  newline position, and `.` still never crosses newlines
- Backreferences (`\1`) are an explicit non-goal: they raise a descriptive
  `RegexError`

### Catastrophic-backtracking protection

Every match attempt runs under a configurable instruction budget
(`compile(pattern, flags, max_steps=...)`, default `100_000_000`).  Exceeding
it raises `RegexTimeoutError`, a subclass of `RegexError`, so patterns such as
`(a+)+$` on long adversarial inputs always terminate promptly instead of
hanging the process.

### Error handling

Invalid patterns raise `RegexError(message, pos)`; `pos` is the 0-based
offset and the string form reports a 1-based column, e.g.
`missing ')' (at column 3)`.  Detected errors include:

- unbalanced/unclosed groups and character classes
- quantifiers with nothing to repeat and stacked quantifiers (`a**`)
- reversed ranges, bad `{m,n}` intervals (`m > n`) and counts over `65535`
- unknown / truncated escapes, duplicate capture names
- unsupported features (backreferences, lookaround, comments)

## Quick start

```python
import rex

p = rex.compile(r"(\w+)@(\w+\.\w+)")
m = p.search("mail bob@example.com now")
m.group()          # 'bob@example.com'
m.group(1)         # 'bob'
m.group(2)         # 'example.com'
m.span()           # (5, 20)

rex.compile(r"<.*?>").findall("<a><b>")        # ['<a>', '<b>']
rex.compile("^\\w+$", rex.M).findall("a\nb")   # ['a', 'b']
rex.compile("ABC", rex.I).fullmatch("abc")     # match
```

## Command line tool

```bash
# pattern + text as arguments
./rex-cli '(\w+)@(\w+\.\w+)' 'mail bob@example.com and sue@x.org'

# text from a file
./rex-cli --multiline '^error:' --file app.log --count

# pattern from stdin's first line, text from the remaining lines
printf '%s\n' '\d+' 'a 1 b 22' | ./rex-cli -

# options
#   -i, --ignore-case    case insensitive matching
#   -m, --multiline      ^ and $ match line edges
#       --findall        one extracted result per line (groups when present)
#       --file PATH      read text from PATH
#       --count          print only the number of matches
#       --max-steps N    override the per-match step budget
```

The default report shows each hit's span, the matched substring, every capture
group and a final `matches: N` count.  The same entry point is available as
`python3 -m rex ...`.

## Running the tests

```bash
python3 -m pytest tests/ -v
```

The suite covers literals/escapes, character classes (ranges, negation, empty
classes), quantifier boundaries (zero/one/bounded/lazy), nested and named
captures, anchor/multiline semantics, alternation preference, invalid-pattern
errors with column assertions, catastrophic-backtracking timeout protection,
lazy `finditer` semantics, empty pattern/input boundaries and CLI end-to-end
behaviour.
