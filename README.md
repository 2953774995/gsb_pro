# regexlab

A mini regular expression engine implemented **from scratch** in pure
Python (standard library only). It provides core `re`-like capabilities
— parsing patterns into an AST and matching them with a backtracking
engine — **without using the `re` module for matching** (a test suite
proves this: importing `regexlab` does not even load `re`).

## Supported syntax

| Feature | Syntax | Notes |
|---|---|---|
| Literals | `abc` | any ordinary character |
| Escapes | `\d \w \s \D \W \S` | ASCII semantics |
| Control escapes | `\n \t \r \f \v \a` | |
| Escaped metachars | `\. \\ \* \[ ...` | literal meaning |
| Any char | `.` | matches anything except `\n` |
| Character classes | `[abc]` `[a-z]` `[^a-z]` | ranges, negation, escapes inside |
| Quantifiers (greedy) | `*` `+` `?` `{m}` `{m,}` `{m,n}` `{,n}` | |
| Quantifiers (lazy) | `*?` `+?` `??` `{m,n}?` | match as little as possible |
| Groups | `(...)` | capturing, numbered left to right |
| Non-capturing groups | `(?:...)` | |
| Alternation | `a|b|c` | leftmost branch preferred, backtracks |
| Anchors | `^` `$` | start / end of string |
| Word boundaries | `\b` `\B` | ASCII word chars |

Not supported (raise `RegexError`): backreferences (`\1`), named groups,
lookaround, flags.

## API

```python
import regexlab

regexlab.match(r"a.c", "abc")            # match at string start
regexlab.search(r"\d+", "a12b3")         # first match anywhere
regexlab.fullmatch(r"\w+", "hello")      # whole string must match
regexlab.findall(r"\d+", "a1b22")        # ['1', '22']
for m in regexlab.finditer(r"\d+", "a1b22"):
    print(m.span())                      # (1, 2) then (3, 5)

p = regexlab.compile(r"(\w+)@(\w+)")     # compiled once, reused
m = p.match("user@host")
m.group(0)      # 'user@host'
m.group(1)      # 'user'
m.groups()      # ('user', 'host')
m.span(2)       # (5, 9)
```

`compile()` results are cached (like `re`), and `Pattern` objects expose
`match / search / fullmatch / findall / finditer` plus a `groups` count.
`Match` objects mimic `re.Match`: `group()`, `groups()`, `start()`,
`end()`, `span()`.

Invalid patterns raise `regexlab.RegexError` with a descriptive message
(and a `pos` attribute when a position is known):

```python
regexlab.compile("(abc")
# RegexError: unbalanced parenthesis: missing ')' (at position 0)
```

## Command-line tool

```bash
# after `pip install .` (provides the regexlab-cli script):
regexlab-cli 'a(b+)c' 'abbc'

# or without installing:
python3 -m regexlab 'a(b+)c' 'abbc'
python3 -m regexlab.cli --mode findall '\d+' 'a1b22'
```

Output:

```
pattern: 'a(b+)c'
text:    'abbc'
mode:    search
result:  MATCH
span:    (0, 4)
matched: 'abbc'
group 1: 'bb'
```

Exit codes: `0` = matched, `1` = no match, `2` = invalid pattern.

## How it works

1. **Parser** (`regexlab/parser.py`): a recursive-descent parser turns
   the pattern string into an AST (`regexlab/ast_nodes.py`). It validates
   the pattern and reports `RegexError` for unbalanced parentheses,
   dangling/duplicate quantifiers, bad ranges, bad escapes, etc.
2. **Engine** (`regexlab/engine.py`): a backtracking matcher written in
   continuation-passing style. Each node tries to match at the current
   position and calls a continuation with the rest of the pattern;
   failure of the continuation triggers backtracking into the next
   alternative. Greedy quantifiers try "more" first, lazy ones try
   "less" first. An empty-iteration guard prevents infinite loops on
   patterns like `(a*)*`. Capture groups copy the group-span list on
   write, so failed branches never leak captures.
3. **Core** (`regexlab/core.py`): `Pattern` (compiled, reusable),
   `Match`, the module-level API and the compile cache.

## Project layout

```
regexlab/
  __init__.py    public API
  errors.py      RegexError
  ast_nodes.py   AST node definitions
  parser.py      pattern string -> AST
  engine.py      backtracking matcher
  core.py        Pattern / Match / module-level functions
  cli.py         regexlab-cli entry point
tests/           pytest suite
```

## Running the tests

```bash
python3 -m pytest tests/ -v
```

The suite covers literals and escapes, character classes and ranges,
greedy vs. lazy quantifiers, groups and captures, alternation, anchors
and word boundaries, error reporting, empty-pattern/empty-match edge
cases, non-overlapping `findall` semantics, the CLI, and a proof that
the `re` module is never imported or used.
