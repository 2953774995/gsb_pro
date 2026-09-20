"""datamask-cli: command-line interface for the datamask engine.

Examples:
    datamask-cli '1[3-9]\\d{9}' '电话 13812345678'
    echo 'a1b2' | datamask-cli '[0-9]' --findall
    datamask-cli --mask phone '联系我 13812345678'
    datamask-cli -i -m '^error' --file ticket.txt
"""

import argparse
import sys

from .errors import PatternError
from .options import IGNORECASE, MULTILINE
from .pattern import compile as compile_pattern
from .rules import get_rule, list_rules


def build_arg_parser():
    p = argparse.ArgumentParser(
        prog="datamask-cli",
        description="敏感信息检测与脱敏工具（自研模式匹配引擎，无第三方依赖）",
    )
    p.add_argument("pattern", nargs="?", help="模式（--mask 模式下为待处理文本）")
    p.add_argument("text", nargs="?", help="待匹配文本（缺省时读 --file 或标准输入）")
    p.add_argument("-i", "--ignore-case", action="store_true",
                   help="忽略大小写")
    p.add_argument("-m", "--multiline", action="store_true",
                   help="多行模式：^/$ 匹配行首/行尾")
    p.add_argument("--findall", action="store_true",
                   help="以 findall 形式输出全部命中")
    p.add_argument("--file", metavar="PATH", help="从文件读取待匹配文本")
    p.add_argument("--mask", metavar="RULE", help="使用内置规则脱敏后直接输出文本")
    p.add_argument("--max-steps", type=int, default=None,
                   help="单次匹配步数上限（默认 100000000）")
    p.add_argument("--list-rules", action="store_true",
                   help="列出全部内置脱敏规则")
    return p


def _read_text(args, positional):
    if positional is not None:
        return positional
    if args.file is not None:
        with open(args.file, "r", encoding="utf-8") as f:
            return f.read()
    return sys.stdin.read()


def main(argv=None):
    args = build_arg_parser().parse_args(argv)

    if args.list_rules:
        for name in list_rules():
            rule = get_rule(name)
            print("%-10s %s" % (name, rule.description))
            print("            pattern: %s" % rule.pattern_text)
        return 0

    try:
        if args.mask:
            rule = get_rule(args.mask)
            text = _read_text(args, args.pattern)
            out = rule.mask_text(text)
            sys.stdout.write(out)
            if not out.endswith("\n"):
                sys.stdout.write("\n")
            return 0

        if args.pattern is None:
            print("datamask-cli: error: pattern is required "
                  "(or use --mask/--list-rules)", file=sys.stderr)
            return 2

        flags = 0
        if args.ignore_case:
            flags |= IGNORECASE
        if args.multiline:
            flags |= MULTILINE
        kwargs = {}
        if args.max_steps is not None:
            kwargs["max_steps"] = args.max_steps
        pattern = compile_pattern(args.pattern, flags, **kwargs)
        text = _read_text(args, args.text)

        if args.findall:
            for item in pattern.findall(text):
                print(repr(item))

        count = 0
        for count, m in enumerate(pattern.finditer(text), 1):
            print("match %d: span=%s text=%r groups=%r"
                  % (count, m.span(), m.group(0), m.groups()))
        print("total: %d match(es)" % count)
        return 0
    except PatternError as exc:
        print("datamask-cli: error: %s" % exc, file=sys.stderr)
        return 2
    except KeyError as exc:
        print("datamask-cli: error: %s" % exc, file=sys.stderr)
        return 2
    except OSError as exc:
        print("datamask-cli: error: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
