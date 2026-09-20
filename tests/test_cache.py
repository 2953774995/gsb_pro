"""缓存：命中、TTL 过期、按类型分 key。"""

from minidns import protocol as P
from minidns.cache import DNSCache


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def make_rr(name="example.com", rtype=P.TYPE_A, ttl=60, addr="1.2.3.4"):
    return P.ResourceRecord(name, rtype, P.CLASS_IN, ttl, P.ARecord(addr))


def test_hit_and_ttl_countdown():
    clock = FakeClock()
    cache = DNSCache(clock=clock)
    key = DNSCache.make_key("Example.COM", P.TYPE_A, P.CLASS_IN)
    cache.put(key, [make_rr(ttl=60)])
    clock.now += 10
    got = cache.get(key)
    assert got is not None
    assert got[0].ttl == 50  # 剩余 TTL 按真实时间折算
    assert got[0].rdata.address == "1.2.3.4"


def test_expiry():
    clock = FakeClock()
    cache = DNSCache(clock=clock)
    key = DNSCache.make_key("example.com", P.TYPE_A, P.CLASS_IN)
    cache.put(key, [make_rr(ttl=30)])
    clock.now += 31
    assert cache.get(key) is None
    assert len(cache) == 0  # 过期条目被清掉


def test_per_record_expiry():
    clock = FakeClock()
    cache = DNSCache(clock=clock)
    key = DNSCache.make_key("example.com", P.TYPE_A, P.CLASS_IN)
    cache.put(key, [make_rr(ttl=10, addr="1.1.1.1"), make_rr(ttl=100, addr="2.2.2.2")])
    clock.now += 20
    got = cache.get(key)
    assert [rr.rdata.address for rr in got] == ["2.2.2.2"]


def test_types_cached_separately():
    cache = DNSCache()
    cache.put(DNSCache.make_key("example.com", P.TYPE_A, P.CLASS_IN), [make_rr()])
    assert cache.get(DNSCache.make_key("example.com", P.TYPE_AAAA, P.CLASS_IN)) is None
    assert cache.get(DNSCache.make_key("example.com", P.TYPE_A, P.CLASS_IN)) is not None


def test_zero_ttl_not_cached():
    cache = DNSCache()
    key = DNSCache.make_key("example.com", P.TYPE_A, P.CLASS_IN)
    cache.put(key, [make_rr(ttl=0)])
    assert cache.get(key) is None


def test_put_message_groups_by_key():
    msg = P.Message()
    msg.answers = [
        make_rr(name="example.com", rtype=P.TYPE_A, addr="1.1.1.1"),
        make_rr(name="example.com", rtype=P.TYPE_A, addr="2.2.2.2"),
        P.ResourceRecord("example.com", P.TYPE_MX, P.CLASS_IN, 60,
                         P.MXRecord(10, "mail.example.com")),
    ]
    cache = DNSCache()
    cache.put_message(msg)
    assert len(cache.get(DNSCache.make_key("example.com", P.TYPE_A, P.CLASS_IN))) == 2
    assert len(cache.get(DNSCache.make_key("example.com", P.TYPE_MX, P.CLASS_IN))) == 1
