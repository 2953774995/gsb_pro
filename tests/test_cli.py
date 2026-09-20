"""CLI 辅助函数测试（不涉及网络的部分）。"""

from minidns import protocol as P
from minidns.cli import _parse_server, _print_message


def test_parse_server():
    assert _parse_server("127.0.0.1:5353") == ("127.0.0.1", 5353)
    assert _parse_server("dns.local:53") == ("dns.local", 53)
    assert _parse_server("127.0.0.1") == ("127.0.0.1", 5353)
    assert _parse_server("[::1]:5353") == ("::1", 5353)


def test_print_message(capsys):
    msg = P.Message()
    msg.id = 1234
    msg.qr = 1
    msg.aa = 1
    msg.ra = 1
    msg.questions.append(P.Question("example.com", P.TYPE_A))
    msg.answers.append(P.ResourceRecord(
        "example.com", P.TYPE_A, P.CLASS_IN, 300, P.ARecord("1.2.3.4")))
    _print_message(msg, 1.5, ("127.0.0.1", 5353))
    out = capsys.readouterr().out
    assert "status: NOERROR" in out
    assert "id: 1234" in out
    assert "example.com." in out
    assert "1.2.3.4" in out
    assert "aa" in out
