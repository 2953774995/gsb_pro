"""zone 文件解析：$ORIGIN/$TTL/@/相对名/括号续行/注释/报错行号/轮询。"""

import pytest

from minidns import protocol as P
from minidns.zone import Zone, ZoneError, load_zone_dir, load_zone_file, parse_ttl

ZONE_TEXT = """
; 顶部注释
$ORIGIN example.com.
$TTL 1h

@       IN  SOA ns1 admin ( 2026092001
                7200 3600 1209600 300 )   ; 多行括号续行
@       IN  NS  ns1
@       IN  NS  ns2
ns1     IN  A   10.0.0.1        ; 行尾注释
www     300 IN  A   192.168.1.10
www     300 IN  A   192.168.1.11
mail    IN  MX  10  mail.example.com.
txt     IN  TXT "hello world"   "k=v;with semicolon"
mail    IN  AAAA  fd00::25
alias   IN  CNAME   www
"""


def parse(text=ZONE_TEXT):
    from minidns.zone import ZoneParser
    return ZoneParser(filename="test.zone").parse_text(text)


def test_origin_and_at():
    zone = parse()
    assert zone.origin == "example.com"
    assert P.TYPE_NS in zone.get_any("example.com")


def test_relative_and_absolute_names():
    zone = parse()
    assert zone.get("ns1.example.com", P.TYPE_A)[0].rdata.address == "10.0.0.1"
    mx = zone.get("mail.example.com", P.TYPE_MX)[0]
    assert mx.rdata.preference == 10
    assert mx.rdata.exchange == "mail.example.com"


def test_multiline_parentheses_and_comments():
    zone = parse()
    soa = zone.get("example.com", P.TYPE_SOA)[0].rdata
    assert soa.mname == "ns1.example.com"
    assert soa.serial == 2026092001
    assert soa.minimum == 300


def test_quoted_txt_with_semicolon():
    zone = parse()
    txt = zone.get("txt.example.com", P.TYPE_TXT)[0].rdata
    assert txt.strings == ["hello world", "k=v;with semicolon"]


def test_ttl_suffix_and_default():
    zone = parse()
    assert zone.get("ns1.example.com", P.TYPE_A)[0].ttl == 3600  # $TTL 1h
    assert zone.get("www.example.com", P.TYPE_A)[0].ttl == 300   # 行内覆盖


def test_ttl_units():
    assert parse_ttl("300", "f", 1) == 300
    assert parse_ttl("1h", "f", 1) == 3600
    assert parse_ttl("2d", "f", 1) == 172800
    with pytest.raises(ZoneError):
        parse_ttl("abc", "f", 1)


def test_round_robin_rotation():
    zone = parse()
    first = [rr.rdata.address for rr in zone.get("www.example.com", P.TYPE_A)]
    second = [rr.rdata.address for rr in zone.get("www.example.com", P.TYPE_A)]
    third = [rr.rdata.address for rr in zone.get("www.example.com", P.TYPE_A)]
    assert first == ["192.168.1.10", "192.168.1.11"]
    assert second == ["192.168.1.11", "192.168.1.10"]  # 轮换起始位置
    assert third == first  # 转完一圈回到起点


def test_error_line_number_unknown_type():
    text = "$ORIGIN example.com.\n\nwww IN FOO 1.2.3.4\n"
    with pytest.raises(ZoneError) as exc:
        parse(text)
    assert exc.value.lineno == 3
    assert "test.zone:3" in str(exc.value)


def test_error_line_number_bad_record():
    text = "$ORIGIN example.com.\nwww IN A not-an-ip\n"
    with pytest.raises(ZoneError) as exc:
        parse(text)
    assert exc.value.lineno == 2


def test_error_unbalanced_parenthesis():
    with pytest.raises(ZoneError):
        parse("$ORIGIN example.com.\n@ IN SOA ns1 admin ( 1 2 3\n")


def test_error_unknown_directive():
    with pytest.raises(ZoneError):
        parse("$ORIGIN example.com.\n$FOO bar\n")


def test_leading_whitespace_reuses_previous_name():
    text = ("$ORIGIN example.com.\n"
            "www IN A 10.0.0.1\n"
            "    IN A 10.0.0.2\n")
    zone = parse(text)
    addrs = {rr.rdata.address for rr in zone.get("www.example.com", P.TYPE_A)}
    assert addrs == {"10.0.0.1", "10.0.0.2"}


def test_load_zone_dir(tmp_path):
    (tmp_path / "example.com.zone").write_text(ZONE_TEXT)
    (tmp_path / "internal.example.com.zone").write_text(
        "$ORIGIN internal.example.com.\n$TTL 60\nweb IN A 10.1.0.8\n")
    zones = load_zone_dir(str(tmp_path))
    assert [z.origin for z in zones] == ["internal.example.com", "example.com"]
    # 文件名推导 origin（没有 $ORIGIN 时）
    (tmp_path / "other.org.zone").write_text("web IN A 10.2.0.1\n")
    zones = load_zone_dir(str(tmp_path))
    origins = {z.origin for z in zones}
    assert "other.org" in origins
