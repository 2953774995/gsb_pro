"""``minisearch-cli``: index a directory of .txt files and query them
interactively.

Usage::

    minisearch-cli <docs_dir> [--top-k N]
    python -m minisearch <docs_dir> [--top-k N]

Each ``.txt`` file (searched recursively) becomes one document whose
doc_id is its path relative to the directory; the first non-empty line is
used as the display title (falling back to the file name).
"""

import argparse
import sys
from pathlib import Path

from .engine import SearchEngine
from .errors import SearchError

_PROMPT = "minisearch> "
_QUIT_COMMANDS = (":q", ":quit", "quit", "exit")


def _iter_text_files(directory):
    return sorted(Path(directory).rglob("*.txt"))


def _extract_title(text, fallback):
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line[:60]
    return fallback


def build_engine(directory):
    """Index every ``.txt`` file under *directory*.

    Returns ``(engine, titles)`` where ``titles`` maps doc_id -> title.
    """
    directory = Path(directory)
    engine = SearchEngine()
    titles = {}
    for path in _iter_text_files(directory):
        text = path.read_text(encoding="utf-8", errors="replace")
        doc_id = str(path.relative_to(directory))
        engine.add_document(doc_id, text)
        titles[doc_id] = _extract_title(text, path.name)
    return engine, titles


def _print_results(results, titles):
    for rank, result in enumerate(results, start=1):
        title = titles.get(result.doc_id, "")
        print("%2d. %s  score=%.4f  %s" % (rank, result.doc_id, result.score, title))
        if result.snippet:
            print("    " + result.snippet)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="minisearch-cli",
        description="Index a directory of .txt files and search them interactively.",
    )
    parser.add_argument("directory", help="directory containing .txt files")
    parser.add_argument(
        "-k", "--top-k", type=int, default=10,
        help="maximum number of results per query (0 = all, default: 10)",
    )
    args = parser.parse_args(argv)

    directory = Path(args.directory)
    if not directory.is_dir():
        print("error: %s is not a directory" % directory, file=sys.stderr)
        return 2

    engine, titles = build_engine(directory)
    print("Indexed %d document(s) from %s" % (engine.document_count(), directory))
    print('Query syntax: term  "exact phrase"  prefix*  AND/OR/NOT  (parentheses)')
    print("Type %s to quit." % " or ".join(_QUIT_COMMANDS[:2]))

    while True:
        try:
            line = input(_PROMPT).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line.lower() in _QUIT_COMMANDS:
            break
        try:
            results = engine.search(line, top_k=args.top_k, with_snippet=True)
        except SearchError as exc:
            print("query error: %s" % exc)
            continue
        if not results:
            print("no results")
        else:
            _print_results(results, titles)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
