"""mdsite 命令行入口：build / serve。"""
from __future__ import annotations

import argparse
import functools
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from . import __version__
from .builder import THEMES, build
from .errors import MdsiteError


def _cmd_build(args) -> int:
    count = build(args.src, args.dst, theme=args.theme)
    print("构建完成：%d 个页面 -> %s（主题: %s）" % (count, args.dst, args.theme))
    return 0


def _cmd_serve(args) -> int:
    directory = os.path.abspath(args.directory)
    if not os.path.isdir(directory):
        raise MdsiteError("预览目录不存在: %s" % directory)
    handler = functools.partial(SimpleHTTPRequestHandler, directory=directory)
    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    except OSError as e:
        raise MdsiteError("无法启动服务（端口 %d）: %s" % (args.port, e.strerror or e)) from e
    print("预览地址: http://127.0.0.1:%d/ （Ctrl+C 停止）" % args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        server.server_close()
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="mdsite", description="纯标准库的 Markdown 静态站点生成器"
    )
    parser.add_argument("--version", action="version", version="mdsite " + __version__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_build = sub.add_parser("build", help="把 Markdown 目录构建成 HTML 站点")
    p_build.add_argument("src", help="输入目录（递归扫描 .md 文件）")
    p_build.add_argument("dst", help="输出目录")
    p_build.add_argument(
        "--theme", default="default", choices=THEMES, help="站点主题（默认 default）"
    )
    p_build.set_defaults(func=_cmd_build)

    p_serve = sub.add_parser("serve", help="本地预览输出目录")
    p_serve.add_argument("directory", help="要预览的目录（通常是 build 的输出目录）")
    p_serve.add_argument("--port", type=int, default=8000, help="端口（默认 8000）")
    p_serve.set_defaults(func=_cmd_serve)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except MdsiteError as e:
        print("错误: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
