"""zone 文件解析与权威查询：$ORIGIN/@/相对名/括号续行/注释/行号报错。"""

import pytest

from minidns.protocol import (RCODE_NOERROR, RCODE_NXDOMAIN, RCODE_SERVFAIL,
                              TYPE_A, TYPE_AAAA, TYPE_CNAME, TYPE_MX, TYPE_NS,
                              TYPE_SOA, TYPE_TXT)
from minidns.zone import Zone, ZoneParseError, ZoneStore, parse_zone

ZONE_TEXT = """
$ORIGIN example.com.
$TTL 600

@       IN  SOA ns1 admin.example.com. (
                1 7200 3600 1209600 300 )
        IN  NS  ns1
        IN  NS  ns2.example.org.   ; 绝对名
ns1     IN  A   10.0.0.1
www     300 IN  A   10.0.0.2
        IN  A   10.0.0.3           ; 空 owner = 上一条的名字
v6      IN  AAAA    2001:db8::1
mail    IN  MX  10 ns1
txt     IN  TXT "hello world" (
            "second" )
web     IN  CNAME   www
"""


def load_store(text=ZONE_TEXT):
    origin, records = parse_zone(text, filename='test.zone')
    zone = Zone(origin)
    for r in records:
        zone.add(r)
    store = ZoneStore()
    store.add_zone(zone)
    return store


def test_origin_and_at():
    store = load_store()
    rcode, answers = store.lookup('example.com', TYPE_NS)
    assert rcode == RCODE_NOERROR
    targets = sorted(r.rdata for r in answers)
    assert targets == ['ns1.example.com.', 'ns2.example.org.']


def test_relative_names_and_ttl():
    store = load_store()
    _, answers = store.lookup('www.example.com', TYPE_A)
    assert sorted(r.rdata for r in answers) == ['10.0.0.2', '10.0.0.3']
    # www 行显式写了 300，覆盖 $TTL 600；空 owner 行继承 $TTL
    ttls = sorted(r.ttl for r in answers)
    assert ttls == [300, 600]


def test_multiline_parentheses_and_comments():
    store = load_store()
    _, soa = store.lookup('example.com', TYPE_SOA)
    assert soa[0].rdata == ('ns1.example.com.', 'admin.example.com.',
                            1, 7200, 3600, 1209600, 300)
    _, txt = store.lookup('txt.example.com', TYPE_TXT)
    assert txt[0].rdata == ['hello world', 'second']


def test_mx_and_aaaa():
    store = load_store()
    _, mx = store.lookup('mail.example.com', TYPE_MX)
    assert mx[0].rdata == (10, 'ns1.example.com.')
    _, aaaa = store.lookup('v6.example.com', TYPE_AAAA)
    assert aaaa[0].rdata == '2001:db8::1'


def test_cname_chain_followed():
    store = load_store()
    rcode, answers = store.lookup('web.example.com', TYPE_A)
    assert rcode == RCODE_NOERROR
    types = [r.type for r in answers]
    assert types == [TYPE_CNAME, TYPE_A, TYPE_A]
    assert answers[0].rdata == 'www.example.com.'
    assert sorted(r.rdata for r in answers[1:]) == ['10.0.0.2', '10.0.0.3']


def test_broken_cname_chain_nxdomain():
    store = load_store("""
$ORIGIN example.com.
lost   IN  CNAME   nowhere
""")
    rcode, answers = store.lookup('lost.example.com', TYPE_A)
    assert rcode == RCODE_NXDOMAIN
    # 应答里仍带上已知的 CNAME 记录
    assert any(r.type == TYPE_CNAME for r in answers)


def test_cname_loop_servfail():
    store = load_store("""
$ORIGIN example.com.
a   IN  CNAME   b
b   IN  CNAME   a
""")
    rcode, _ = store.lookup('a.example.com', TYPE_A)
    assert rcode == RCODE_SERVFAIL


def test_nxdomain_vs_nodata():
    store = load_store()
    # 名字存在但没有 AAAA -> NOERROR 空应答（NODATA）
    rcode, answers = store.lookup('ns1.example.com', TYPE_AAAA)
    assert rcode == RCODE_NOERROR and answers == []
    # 名字不存在 -> NXDOMAIN
    rcode, _ = store.lookup('nope.example.com', TYPE_A)
    assert rcode == RCODE_NXDOMAIN


def test_out_of_zone_returns_none():
    store = load_store()
    assert store.lookup('other.org', TYPE_A) is None


def test_round_robin_rotation():
    store = load_store()
    firsts = []
    for _ in range(4):
        _, answers = store.lookup('www.example.com', TYPE_A)
        firsts.append(answers[0].rdata)
    # 两条记录轮换起始位置
    assert firsts[0] != firsts[1]
    assert firsts[0] == firsts[2]
    assert firsts[1] == firsts[3]
    assert set(firsts) == {'10.0.0.2', '10.0.0.3'}


def test_parse_error_reports_line_number():
    text = "$ORIGIN example.com.\n\nwww IN A not-an-ip\n"
    with pytest.raises(ZoneParseError) as excinfo:
        parse_zone(text, filename='bad.zone')
    assert excinfo.value.lineno == 3
    assert 'bad.zone' in str(excinfo.value)


def test_unknown_directive_rejected():
    with pytest.raises(ZoneParseError):
        parse_zone("$FOO bar\n", filename='x.zone')


def test_unbalanced_parentheses_rejected():
    with pytest.raises(ZoneParseError):
        parse_zone("$ORIGIN example.com.\n@ IN TXT ( \"a\"\n", filename='x.zone')


def test_multiple_zones_in_store(tmp_path):
    d = tmp_path / 'zones'
    d.mkdir()
    (d / 'a.zone').write_text(
        "$ORIGIN a.test.\n@ IN A 1.1.1.1\n")
    (d / 'b.zone').write_text(
        "$ORIGIN b.test.\n@ IN A 2.2.2.2\n")
    store = ZoneStore()
    loaded = store.load_dir(str(d))
    assert len(loaded) == 2
    assert store.lookup('a.test', TYPE_A)[1][0].rdata == '1.1.1.1'
    assert store.lookup('b.test', TYPE_A)[1][0].rdata == '2.2.2.2'
