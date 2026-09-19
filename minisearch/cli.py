"""minisearch-cli: index a directory of .txt files and search interactively.

Usage:
    minisearch-cli <directory> [--no-stopwords]
    python3 -m minisearch.cli <directory>

Interactive commands:
    any text            run a query (boolean / phrase / prefix supported)
    :remove <doc_id>    remove a document from the index
    :count              show the number of indexed documents
    :help               show help
    :quit               exit
"""

import argparse
import os
import sys

from .engine import SearchEngine
from .errors import SearchError

HELP = """\
Query syntax:
  term                 single word, e.g.  python
  t1 AND t2            both must match        t1 OR t2   either may match
  NOT t                exclude matches        ( ... )    grouping
  "exact phrase"       adjacent words         pref*      prefix match
Commands: :remove <doc_id>  :count  :help  :quit
"""


def build_engine_from_dir(directory, use_stopwords=True):
    """Index every .txt file in ``directory``; doc_id is the file name."""
    engine = SearchEngine(use_stopwords=use_stopwords)
    for name in sorted(os.listdir(directory)):
        path = os.path.join(directory, name)
        if not (os.path.isfile(path) and name.lower().endswith(".txt")):
            continue
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            engine.add_document(name, handle.read())
    return engine


def title_of(text):
    """First non-empty line of a document, used as its display title."""
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ""


def run_query(engine, query, top_k=10, with_snippet=True):
    return engine.search(query, top_k=top_k, with_snippet=with_snippet)


def print_results(results, engine, out):
    if not results:
        print("  (no hits)", file=out)
        return
    for rank, hit in enumerate(results, 1):
        doc_id = hit["doc_id"]
        title = title_of(engine.index.documents.get(doc_id, ""))
        header = "%2d. %s  (score %.4f)" % (rank, doc_id, hit["score"])
        if title and title != str(doc_id):
            header += "  -- " + title[:60]
        print(header, file=out)
        snippet = hit.get("snippet")
        if snippet:
            print("     " + snippet.replace("\n", " "), file=out)


def repl(engine, input_fn=None, out=None, top_k=10):
    if input_fn is None:
        input_fn = input
    if out is None:
        out = sys.stdout
    print("Indexed %d documents. Type :help for syntax, :quit to exit."
          % engine.document_count(), file=out)
    while True:
        try:
            line = input_fn("minisearch> ")
        except (EOFError, KeyboardInterrupt):
            print("", file=out)
            break
        query = line.strip()
        if not query:
            continue
        if query.startswith(":"):
            command, _, arg = query[1:].partition(" ")
            command, arg = command.lower(), arg.strip()
            if command in ("quit", "exit", "q"):
                break
            if command == "help":
                print(HELP, file=out)
            elif command == "count":
                print("  %d documents" % engine.document_count(), file=out)
            elif command == "remove":
                if engine.remove_document(arg):
                    print("  removed %r" % arg, file=out)
                else:
                    print("  no such document: %r" % arg, file=out)
            else:
                print("  unknown command, try :help", file=out)
            continue
        try:
            results = run_query(engine, query, top_k=top_k)
        except SearchError as exc:
            print("  query error: %s" % exc, file=out)
            continue
        print_results(results, engine, out)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="minisearch-cli",
        description="Index a directory of .txt files and search them.",
    )
    parser.add_argument("directory", help="directory containing .txt files")
    parser.add_argument("--no-stopwords", action="store_true",
                        help="disable stop-word filtering")
    parser.add_argument("--top-k", type=int, default=10,
                        help="max hits per query (0 = all, default 10)")
    args = parser.parse_args(argv)
    if not os.path.isdir(args.directory):
        parser.error("not a directory: %s" % args.directory)
    engine = build_engine_from_dir(args.directory,
                                   use_stopwords=not args.no_stopwords)
    repl(engine, top_k=args.top_k)
    return 0


if __name__ == "__main__":
    sys.exit(main())
