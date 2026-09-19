"""Command line interface for minisearch.

Usage:
    minisearch-cli <directory> [--top-k N] [--no-stem] [--no-stop-words]

Scans the directory recursively for .txt files, indexes them (doc_id is
the file path relative to the directory; the first non-empty line is
shown as the title), then starts an interactive query loop.
"""

import argparse
import os
import sys

from .engine import SearchEngine
from .query import SearchError


def build_index(directory, engine):
    """Index every .txt file under directory. Returns {doc_id: title}."""
    titles = {}
    for root, _dirs, files in os.walk(directory):
        for name in sorted(files):
            if not name.lower().endswith(".txt"):
                continue
            path = os.path.join(root, name)
            doc_id = os.path.relpath(path, directory)
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as handle:
                    text = handle.read()
            except OSError as exc:
                print("warning: skipping %s (%s)" % (doc_id, exc), file=sys.stderr)
                continue
            title = ""
            for line in text.splitlines():
                if line.strip():
                    title = line.strip()
                    break
            engine.add_document(doc_id, text)
            titles[doc_id] = title or name
    return titles


def run_repl(engine, titles, top_k):
    print("Indexed %d document(s). Enter a query, or 'quit' to exit." % engine.document_count())
    while True:
        try:
            query = input("minisearch> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not query:
            continue
        if query.lower() in ("quit", "exit", ":q"):
            break
        try:
            results = engine.search(query, top_k=top_k, with_snippet=True)
        except SearchError as exc:
            print("query error: %s" % exc)
            continue
        if not results:
            print("  (no results)")
            continue
        for rank, result in enumerate(results, 1):
            doc_id = result["doc_id"]
            title = titles.get(doc_id, "")
            print("%2d. %s  (score: %.4f)" % (rank, doc_id, result["score"]))
            if title:
                print("    title: %s" % title)
            print("    %s" % result["snippet"])


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="minisearch-cli",
        description="Index a directory of .txt files and search them interactively.")
    parser.add_argument("directory", help="directory to scan for .txt files")
    parser.add_argument("--top-k", type=int, default=10,
                        help="maximum number of results (0 = all, default 10)")
    parser.add_argument("--no-stem", action="store_true",
                        help="disable English stemming")
    parser.add_argument("--no-stop-words", action="store_true",
                        help="disable stop-word filtering")
    args = parser.parse_args(argv)

    if not os.path.isdir(args.directory):
        print("error: %s is not a directory" % args.directory, file=sys.stderr)
        return 2

    engine = SearchEngine(use_stop_words=not args.no_stop_words,
                          stem=not args.no_stem)
    titles = build_index(args.directory, engine)
    run_repl(engine, titles, args.top_k)
    return 0


if __name__ == "__main__":
    sys.exit(main())
