"""Command-line interface for building and querying offline indexes."""
from __future__ import annotations

import argparse
import os
import sys
from typing import List

from .engine import KBSearch
from .errors import SearchError

DEFAULT_INDEX = os.path.join(".kbsearch", "index.json")
SYNONYM_FILE = os.path.join("config", "synonyms.txt")


def _load_or_create(args) -> KBSearch:
    # --reindex rebuilds postings but preserves the stored analyzer/synonym
    # settings.  The stop-word option only applies when creating an index.
    if os.path.exists(args.index):
        return KBSearch.load(args.index)
    return KBSearch(use_stopwords=not args.keep_stopwords)


def _apply_synonyms(engine: KBSearch, explicit: str = None,
                    directory: str = None) -> None:
    candidates = []
    if explicit:
        candidates.append(explicit)
    else:
        preferred = os.path.join(directory, "synonyms.txt") if directory else None
        if preferred and os.path.exists(preferred):
            candidates.append(preferred)
        if os.path.exists(SYNONYM_FILE):
            candidates.append(SYNONYM_FILE)
    for path in candidates:
        engine.load_synonyms(path)


def _print_result(result: dict, verbose: bool = False) -> None:
    line = "doc_id=%s score=%.6f" % (result["doc_id"], result["score"])
    print(line)
    if verbose and result.get("snippet"):
        print("  " + result["snippet"])


def run_build(args) -> int:
    engine = _load_or_create(args)
    # Reindex rebuilds only directory-owned documents, but still preserves
    # synonym configuration unless the user supplies a replacement file.
    if args.synonyms:
        engine.synonyms = type(engine.synonyms)(engine.analyzer)
        engine.load_synonyms(args.synonyms)
    else:
        _apply_synonyms(engine, None, args.directory)
    stats = engine.index_directory(args.directory, reindex=args.reindex)
    engine.save(args.index)
    print("已建立/更新索引: %s" % args.index)
    print("txt 文件=%(files)d 新增=%(added)d 更新=%(updated)d 未变=%(unchanged)d" % stats)
    print("文档总数=%d" % engine.document_count())
    return 0


def run_update(args) -> int:
    if not os.path.exists(args.index):
        raise FileNotFoundError("索引不存在，请先使用 --directory 批量建索引: %s" % args.index)
    engine = KBSearch.load(args.index)
    changed = engine.update_file(args.update, force=True)
    engine.save(args.index)
    print("增量更新完成，文件是否发生变化: %s" % ("是" if changed else "否（已强制重建）"))
    print("文档总数=%d" % engine.document_count())
    return 0


def run_query(args) -> int:
    engine = KBSearch.load(args.index)
    _apply_synonyms(engine, args.synonyms, None)
    results = engine.search(args.query, top_k=args.top_k, with_snippet=True)
    if not results:
        print("无命中")
        return 0
    for result in results:
        _print_result(result, verbose=True)
    return 0


def run_interactive(engine: KBSearch, top_k: int) -> int:
    print("kbsearch 离线检索（输入 :help 查看帮助，:quit 退出）")
    print("文档数: %d" % engine.document_count())
    while True:
        try:
            query = input("query> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not query:
            continue
        if query in (":quit", ":q", ":exit"):
            return 0
        if query == ":help":
            print("示例: 压缩机 AND (异响 OR 不制冷)")
            print('短语: "not cooling"；前缀: comp*；NOT: NOT 空调')
            continue
        try:
            results = engine.search(query, top_k=top_k, with_snippet=True)
        except SearchError as exc:
            print("查询错误: %s" % exc, file=sys.stderr)
            continue
        if not results:
            print("无命中")
            continue
        for result in results:
            _print_result(result, verbose=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kbsearch-cli",
        description="离线售后知识库检索工具（仅依赖 Python 标准库）")
    parser.add_argument("--index", default=DEFAULT_INDEX,
                        help="索引 JSON 路径，默认 .kbsearch/index.json")
    parser.add_argument("--directory", help="扫描该目录下的 .txt 文件")
    parser.add_argument("--reindex", action="store_true",
                        help="全量重建目录中文档的索引")
    parser.add_argument("--update", metavar="FILE",
                        help="只增量重建指定 txt 文件的 postings")
    parser.add_argument("--synonyms", help="同义词配置文件，每行 A=B=C")
    parser.add_argument("--query", help="执行一次查询后退出")
    parser.add_argument("--top-k", type=int, default=10,
                        help="返回结果数，默认 10；0 表示全部")
    parser.add_argument("--interactive", action="store_true",
                        help="进入交互式查询（加载索引后的默认模式）")
    parser.add_argument("--keep-stopwords", action="store_true",
                        help="建索引时不启用英文停止词过滤（默认启用）")
    return parser


def main(argv: List[str] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.update:
            return run_update(args)
        if args.directory:
            run_build(args)
            if args.query:
                return run_query(args)
            if args.interactive:
                engine = KBSearch.load(args.index)
                _apply_synonyms(engine, args.synonyms, None)
                return run_interactive(engine, args.top_k)
            return 0
        if not os.path.exists(args.index):
            parser.error("索引不存在；请使用 --directory <txt目录> 建索引，或指定 --index")
        engine = KBSearch.load(args.index)
        _apply_synonyms(engine, args.synonyms, None)
        if args.query:
            results = engine.search(args.query, top_k=args.top_k,
                                    with_snippet=True)
            if not results:
                print("无命中")
            else:
                for result in results:
                    _print_result(result, verbose=True)
            return 0
        return run_interactive(engine, args.top_k)
    except (OSError, ValueError, TypeError) as exc:
        print("错误: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
