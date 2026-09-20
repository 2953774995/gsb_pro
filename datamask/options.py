"""Compile options and shared constants."""

# Flag values intentionally mirror the stdlib `re` module so the API
# feels familiar, but the implementation is 100% our own.
IGNORECASE = I = 2
MULTILINE = M = 8

#: Default per-match step budget (100 million) guarding against
#: catastrophic backtracking.  Configurable via compile(..., max_steps=).
DEFAULT_MAX_STEPS = 100_000_000

#: Largest quantifier bound allowed by the parser: {m,n} with n <= 65535.
MAX_REPEAT = 65535
