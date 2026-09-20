"""递归应答的 TTL 缓存。

key = (小写名字, 类型, 类)；每条记录带自己的 TTL，到期自动失效。
TTL 倒计时用真实时间（clock 可注入，方便测试）。
"""

import threading
import time


class DNSCache:
    def __init__(self, clock=None):
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()
        # key -> (stored_at, [ResourceRecord])
        self._entries = {}

    @staticmethod
    def make_key(name, rtype, rclass):
        return (name.lower(), rtype, rclass)

    def get(self, key):
        """命中返回 TTL 已按剩余时间折算的记录副本；未命中/全过期返回 None。"""
        now = self._clock()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            stored_at, records = entry
            fresh = []
            for rr in records:
                remaining = rr.ttl - (now - stored_at)
                if remaining > 0:
                    fresh.append(rr.copy_with_ttl(int(remaining)))
            if not fresh:
                del self._entries[key]
                return None
            return fresh

    def put(self, key, records):
        """写入一组记录（按各自 TTL 计期）；TTL<=0 的不缓存。"""
        records = [rr for rr in records if rr.ttl > 0]
        if not records:
            return
        with self._lock:
            self._entries[key] = (self._clock(), list(records))

    def put_message(self, message):
        """把应答报文 Answer 段的记录按 (name, type, class) 分组缓存。"""
        groups = {}
        for rr in message.answers:
            key = self.make_key(rr.name, rr.rtype, rr.rclass)
            groups.setdefault(key, []).append(rr)
        for key, records in groups.items():
            self.put(key, records)

    def __len__(self):
        return len(self._entries)

    def clear(self):
        with self._lock:
            self._entries.clear()
