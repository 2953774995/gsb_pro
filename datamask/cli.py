"""datamask-cli：命令行入口。

用法示例：
    datamask-cli '\\d{4}' '工单 1234 与 5678'
    echo 'aBc' | datamask-cli --ignore-case 'abc'
    datamask-cli --mask mobile '联系电话 13812345678'
    datamask-cli --file ticket.txt '(?P<id>\\d{6})'
"""

import argparse
import sys

from .errors import PatternError
from .pattern import DEFAULT_MAX_STEPS, IGNORECASE, MULTILINE, compile
from .rules import RULES, mask


def _build_parser():
    parser = argparse.ArgumentParser(
        prog="datamask-cli",
        description="敏感信息检测与脱敏工具（自研模式引擎，不使用 re 模块）",
    )
    parser.add_argument("pattern", nargs="?",
                        help="datamask 模式语法；--mask 模式下此位置为待处理文本")
    parser.add_argument("text", nargs="?",
                        help="待搜索文本；缺省时从标准输入读取")
    parser.add_argument("-i", "--ignore-case", action="store_true",
                        help="忽略大小写")
    parser.add_argument("-m", "--multiline", action="store_true",
                        help="多行模式：^/$ 匹配行首/行尾")
    parser.add_argument("--findall", action="store_true",
                        help="以 findall 语义列出全部命中内容")
    parser.add_argument("--file", metavar="PATH",
                        help="从文件读取待处理文本")
    parser.add_argument("--mask", metavar="RULES",
                        help="脱敏模式：逗号分隔的规则名或 all"
                             "（可用规则：%s）" % ", ".join(sorted(RULES)))
    parser.add_argument("--max-steps", type=int, default=DEFAULT_MAX_STEPS,
                        help="单次匹配步数上限（默认 %(default)s）")
    return parser


def _read_text(args, parser):
    if args.file is not None:
        try:
            with open(args.file, "r", encoding="utf-8") as f:
                return f.read()
        except OSError as exc:
            print("error: cannot read %s: %s" % (args.file, exc),
                  file=sys.stderr)
            return None
    if args.mask:
        # --mask 模式下第一个位置参数即待处理文本
        if args.text is not None:
            parser.error("too many arguments in --mask mode")
        if args.pattern is not None:
            return args.pattern
    elif args.text is not None:
        return args.text
    return sys.stdin.read()


def _run_mask(args, text):
    names = args.mask.strip()
    if names == "all":
        rule_names = "all"
    else:
        rule_names = [n.strip() for n in names.split(",") if n.strip()]
        if not rule_names:
            raise PatternError("empty rule list for --mask")
    masked = mask(text, rule_names)
    sys.stdout.write(masked)
    if not masked.endswith("\n"):
        sys.stdout.write("\n")
    return 0


def _run_search(args, text):
    if args.pattern is None:
        _build_parser().error("pattern is required (unless --mask is given)")
    flags = 0
    if args.ignore_case:
        flags |= IGNORECASE
    if args.multiline:
        flags |= MULTILINE
    pattern = compile(args.pattern, flags, max_steps=args.max_steps)
    matches = list(pattern.finditer(text))
    if args.findall:
        for item in pattern.findall(text):
            print(repr(item))
    for i, m in enumerate(matches, 1):
        print("match %d: span=(%d, %d) text=%r"
              % (i, m.start(), m.end(), m.group(0)))
        if pattern.groups:
            print("  groups: %r" % (m.groups(),))
            for name, index in sorted(pattern.groupindex.items(),
                                      key=lambda kv: kv[1]):
                print("  group %r: %r" % (name, m.group(name)))
    print("count: %d" % len(matches))
    return 0 if matches else 1


def main(argv=None):
    parser = _build_parser()
    args = parser.parse_args(argv)
    text = _read_text(args, parser)
    if text is None:
        return 2
    try:
        if args.mask:
            return _run_mask(args, text)
        return _run_search(args, text)
    except PatternError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
