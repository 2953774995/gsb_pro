import sys

from .repl import run

if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))
