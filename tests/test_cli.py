from gwadmin.cli import build_parser


def test_cli_required_arguments():
    args = build_parser().parse_args(["--host", "127.0.0.1", "--port", "9090", "--root", "web", "--workers", "4"])
    assert args.host == "127.0.0.1"
    assert args.port == 9090
    assert args.root == "web"
    assert args.workers == 4
