"""命令行入口：mdsite build / mdsite serve。"""

import argparse
import functools
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import __version__
from .builder import MdsiteError, available_themes, build


def _cmd_build(args):
    count = build(args.input, args.output, theme=args.theme,
                  site_name=args.site_name)
    print("构建完成: %d 个页面 -> %s" % (count, args.output))
    return 0


def _port(value):
    try:
        port = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("端口必须是 0-65535 的整数")
    if not 0 <= port <= 65535:
        raise argparse.ArgumentTypeError("端口必须在 0-65535 之间")
    return port


def _cmd_serve(args):
    directory = Path(args.directory)
    if not directory.is_dir():
        raise MdsiteError("目录不存在: %s（先运行 mdsite build）" % directory)
    handler = functools.partial(SimpleHTTPRequestHandler,
                                directory=str(directory))
    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    except OSError as e:
        raise MdsiteError("无法启动服务（端口 %d）: %s" % (args.port, e))
    url = "http://127.0.0.1:%d/" % args.port
    print("预览 %s -> %s （Ctrl+C 停止）" % (directory, url))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        server.server_close()
    return 0


def make_parser():
    parser = argparse.ArgumentParser(
        prog="mdsite",
        description="把 Markdown 文档目录构建成静态 HTML 站点。")
    parser.add_argument("--version", action="version",
                        version="mdsite " + __version__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_build = sub.add_parser("build", help="构建站点")
    p_build.add_argument("input", help="Markdown 输入目录")
    p_build.add_argument("output", help="HTML 输出目录")
    p_build.add_argument("--theme", default="default",
                         help="主题（可选: %s）" % ", ".join(available_themes()))
    p_build.add_argument("--site-name", default=None, help="站点名称")
    p_build.set_defaults(func=_cmd_build)

    p_serve = sub.add_parser("serve", help="本地预览已构建的站点")
    p_serve.add_argument("directory", help="构建输出目录")
    p_serve.add_argument("--port", type=_port, default=8000, help="端口（默认 8000）")
    p_serve.set_defaults(func=_cmd_serve)
    return parser


def main(argv=None):
    args = make_parser().parse_args(argv)
    try:
        return args.func(args)
    except MdsiteError as e:
        print("mdsite: 错误: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
