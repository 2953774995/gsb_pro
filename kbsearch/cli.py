"""kbsearch-cli: build / update / query an index from the command line.

Usage examples::

    kbsearch-cli --dir ./manuals --index kb.json --synonyms syn.txt
    kbsearch-cli --dir ./manuals --index kb.json --reindex
    kbsearch-cli --index kb.json --update ./manuals/a01.txt
    kbsearch-cli --index kb.json            # interactive search
"""

import argparse
import os
import sys

from .core import KBSearch
from .errors import SearchError
from .synonyms import SynonymMap

DEFAULT_INDEX = "kbsearch.index.json"


def _doc_id_for(root, path):
    return os.path.splitext(os.path.relpath(path, root))[0]


def _title_for(path, text):
    for line in text.splitlines():
        if line.strip():
            return line.strip()[:80]
    return os.path.basename(path)


def build_from_dir(kb, directory):
    """Index every ``.txt`` file under *directory* (skips unchanged files)."""
    indexed = 0
    skipped = 0
    for dirpath, _dirs, files in os.walk(directory):
        for name in sorted(files):
            if not name.lower().endswith(".txt"):
                continue
            path = os.path.join(dirpath, name)
            doc_id = _doc_id_for(directory, path)
            mtime = os.path.getmtime(path)
            meta = kb.index.doc_meta.get(doc_id, {})
            if meta.get("mtime") == mtime and meta.get("source") == os.path.abspath(path):
                skipped += 1
                continue
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            kb.add_document(
                doc_id,
                text,
                meta={
                    "source": os.path.abspath(path),
                    "title": _title_for(path, text),
                    "mtime": mtime,
                },
            )
            indexed += 1
    return indexed, skipped


def update_file(kb, path):
    """Incrementally re-index a single file (only its postings are rebuilt)."""
    abspath = os.path.abspath(path)
    doc_id = None
    for d, meta in kb.index.doc_meta.items():
        if meta.get("source") == abspath:
            doc_id = d
            break
    if doc_id is None:
        doc_id = os.path.splitext(os.path.basename(path))[0]
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    kb.add_document(
        doc_id,
        text,
        meta={
            "source": abspath,
            "title": _title_for(path, text),
            "mtime": os.path.getmtime(path),
        },
    )
    return doc_id


def print_results(kb, results, out):
    if not results:
        out.write("(no results)\n")
        return
    for rank, hit in enumerate(results, 1):
        doc_id = hit["doc_id"]
        title = kb.index.doc_meta.get(doc_id, {}).get("title", "")
        header = "%2d. doc_id=%s  score=%.4f" % (rank, doc_id, hit["score"])
        if title:
            header += "  | %s" % title
        out.write(header + "\n")
        snippet = hit.get("snippet")
        if snippet:
            out.write("    %s\n" % snippet)


def repl(kb, top_k=10, out=None):
    out = out or sys.stdout
    out.write("kbsearch interactive mode. Type a query, 'quit' to exit.\n")
    while True:
        try:
            line = input("kbsearch> ")
        except EOFError:
            break
        line = line.strip()
        if not line:
            continue
        if line.lower() in ("quit", "exit"):
            break
        try:
            results = kb.search(line, top_k=top_k, with_snippet=True)
        except SearchError as exc:
            out.write("query error: %s\n" % exc)
            continue
        print_results(kb, results, out)
    out.write("bye\n")


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="kbsearch-cli",
        description="Offline after-sales knowledge-base search (stdlib only).",
    )
    parser.add_argument("--dir", help="directory of .txt documents to index")
    parser.add_argument("--index", default=DEFAULT_INDEX, help="index file path")
    parser.add_argument("--synonyms", help="synonym file (one group per line, a=b=c)")
    parser.add_argument(
        "--reindex",
        action="store_true",
        help="rebuild the index from scratch (requires --dir)",
    )
    parser.add_argument("--update", metavar="FILE", help="incrementally re-index one file")
    parser.add_argument("--top-k", type=int, default=10, help="max hits to show (0 = all)")
    args = parser.parse_args(argv)

    synonyms = SynonymMap.from_file(args.synonyms) if args.synonyms else SynonymMap()

    if args.update:
        if not os.path.exists(args.index):
            parser.error("--update requires an existing index file: %s" % args.index)
        kb = KBSearch.load(args.index, synonyms=synonyms)
        doc_id = update_file(kb, args.update)
        kb.save(args.index)
        print("updated document: %s (total %d docs)" % (doc_id, kb.document_count()))
        return 0

    if args.dir:
        if args.reindex or not os.path.exists(args.index):
            kb = KBSearch(synonyms=synonyms)
        else:
            kb = KBSearch.load(args.index, synonyms=synonyms)
        indexed, skipped = build_from_dir(kb, args.dir)
        kb.save(args.index)
        print(
            "indexed %d file(s), %d unchanged, %d docs total -> %s"
            % (indexed, skipped, kb.document_count(), args.index)
        )
    else:
        if not os.path.exists(args.index):
            parser.error("index not found: %s (use --dir to build one)" % args.index)
        kb = KBSearch.load(args.index, synonyms=synonyms)
        print("loaded %d docs from %s" % (kb.document_count(), args.index))

    repl(kb, top_k=args.top_k)
    return 0


if __name__ == "__main__":
    sys.exit(main())
