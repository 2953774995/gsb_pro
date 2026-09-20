"""缓存：命中、TTL 过期、按类型分开、singleflight 合并。"""

import threading
import time

from minidns.cache import Cache
from minidns.protocol import (CLASS_IN, TYPE_A, TYPE_AAAA, TYPE_TXT, Record)


class FakeClock(object):
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def make_rec(name='www.example.com.', rtype=TYPE_A, ttl=60, rdata='1.2.3.4'):
    return Record(name, rtype, CLASS_IN, ttl, rdata)


def test_cache_hit_and_remaining_ttl():
    clock = FakeClock()
    cache = Cache(now=clock)
    cache.put_records([make_rec(ttl=60)])
    clock.t += 10
    got = cache.get('www.example.com', TYPE_A)
    assert got is not None
    assert got[0].rdata == '1.2.3.4'
    assert got[0].ttl == 50  # 剩余 TTL 用真实时间倒计时


def test_cache_expires():
    clock = FakeClock()
    cache = Cache(now=clock)
    cache.put_records([make_rec(ttl=30)])
    assert cache.get('www.example.com', TYPE_A) is not None
    clock.t += 31
    assert cache.get('www.example.com', TYPE_A) is None


def test_cache_real_time_expiry():
    cache = Cache()  # 真实时钟
    cache.put_records([make_rec(ttl=1)])
    assert cache.get('www.example.com', TYPE_A) is not None
    time.sleep(1.1)
    assert cache.get('www.example.com', TYPE_A) is None


def test_cache_miss_unknown_name():
    cache = Cache()
    cache.put_records([make_rec()])
    assert cache.get('other.example.com', TYPE_A) is None


def test_cache_separated_by_type():
    cache = Cache()
    cache.put_records([make_rec(rtype=TYPE_A, rdata='1.2.3.4')])
    cache.put_records([make_rec(rtype=TYPE_TXT, rdata=['hello'])])
    assert cache.get('www.example.com', TYPE_A)[0].rdata == '1.2.3.4'
    assert cache.get('www.example.com', TYPE_TXT)[0].rdata == ['hello']
    assert cache.get('www.example.com', TYPE_AAAA) is None


def test_cache_case_insensitive():
    cache = Cache()
    cache.put_records([make_rec(name='WWW.Example.COM')])
    assert cache.get('www.example.com', TYPE_A) is not None


def test_cache_multiple_records_same_key():
    cache = Cache()
    cache.put_records([make_rec(rdata='1.1.1.1'), make_rec(rdata='2.2.2.2')])
    got = cache.get('www.example.com', TYPE_A)
    assert sorted(r.rdata for r in got) == ['1.1.1.1', '2.2.2.2']


def test_cache_zero_ttl_not_stored():
    cache = Cache()
    cache.put_records([make_rec(ttl=0)])
    assert cache.get('www.example.com', TYPE_A) is None


def test_cache_thread_safe():
    cache = Cache()
    errors = []

    def worker(n):
        try:
            for i in range(200):
                cache.put_records([make_rec(name='n%d.example.com.' % (n % 5),
                                            rdata='10.0.0.%d' % i)])
                cache.get('n%d.example.com.' % (n % 5), TYPE_A)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
