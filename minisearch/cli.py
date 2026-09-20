"""minisearch 命令行工具：从目录批量建索引并交互式查询。"""

import argparse
import os
import sys

from .engine import SearchEngine
from .errors import SearchError


def build_index(directory, use_stopwords=True):
    """扫描目录下全部 .txt 文件建索引。

    doc_id 为文件名（不含扩展名）；标题取正文首个非空行，无则退回文件名。
    返回 (engine, titles)。
    """
    engine = SearchEngine(use_stopwords=use_stopwords)
    titles = {}
    for filename in sorted(os.listdir(directory)):
        if not filename.lower().endswith(".txt"):
            continue
        path = os.path.join(directory, filename)
        if not os.path.isfile(path):
            continue
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        doc_id = os.path.splitext(filename)[0]
        title = next((line.strip() for line in text.splitlines() if line.strip()), doc_id)
        engine.add_document(doc_id, text)
        titles[doc_id] = title
    return engine, titles


def print_results(results, titles):
    if not results:
        print("  （无命中）")
        return
    for rank, item in enumerate(results, 1):
        doc_id = item["doc_id"]
        title = titles.get(doc_id, doc_id)
        print("  %2d. [%s] %s  score=%.4f" % (rank, doc_id, title, item["score"]))
        snippet = item.get("snippet")
        if snippet:
            print("      %s" % snippet)


def repl(engine, titles):
    print("已索引 %d 篇文档。输入查询开始检索（支持 AND/OR/NOT/括号/\"短语\"/前缀*）。" % engine.document_count())
    print("命令：:remove <doc_id> 删除文档，:count 查看文档数，:quit 退出。")
    while True:
        try:
            line = input("minisearch> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line in (":quit", ":exit", "quit", "exit"):
            break
        if line == ":count":
            print("  文档数：%d" % engine.document_count())
            continue
        if line.startswith(":remove "):
            doc_id = line[len(":remove "):].strip()
            if engine.remove_document(doc_id):
                titles.pop(doc_id, None)
                print("  已删除 %r，当前文档数：%d" % (doc_id, engine.document_count()))
            else:
                print("  文档 %r 不存在" % doc_id)
            continue
        try:
            results = engine.search(line, top_k=10, with_snippet=True)
        except SearchError as exc:
            print("  查询错误：%s" % exc)
            continue
        print_results(results, titles)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="minisearch-cli",
        description="从目录批量索引 .txt 文件并交互式全文检索",
    )
    parser.add_argument("directory", help="包含 .txt 文档的目录")
    parser.add_argument(
        "--no-stopwords", action="store_true", help="关闭停止词过滤"
    )
    args = parser.parse_args(argv)
    if not os.path.isdir(args.directory):
        print("错误：目录不存在：%s" % args.directory, file=sys.stderr)
        return 2
    engine, titles = build_index(args.directory, use_stopwords=not args.no_stopwords)
    repl(engine, titles)
    return 0


if __name__ == "__main__":
    sys.exit(main())
