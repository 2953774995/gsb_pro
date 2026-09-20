"""按 (名字, 类型, 类) 为 key 的 TTL 缓存，TTL 用真实时间倒计时。"""

import threading
import time

from .protocol import CLASS_IN, normalize_name


class Cache(object):
    def __init__(self, now=time.time):
        self._now = now  # 可注入时钟，方便测试
        self._data = {}  # (name, rtype, rclass) -> (expire, [Record])
        self._lock = threading.Lock()

    def get(self, name, rtype, rclass=CLASS_IN):
        """命中返回带剩余 TTL 的记录副本列表；未命中/过期返回 None。"""
        key = (normalize_name(name), rtype, rclass)
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            expire, records = entry
            remaining = expire - self._now()
            if remaining <= 0:
                del self._data[key]
                return None
            return [rec.copy_with_ttl(int(remaining)) for rec in records]

    def put_records(self, records):
        """把一组记录按各自 TTL 缓存（TTL=0 的不缓存）。"""
        now = self._now()
        with self._lock:
            for rec in records:
                if rec.ttl <= 0:
                    continue
                key = (rec.name, rec.type, rec.rclass)
                expire = now + rec.ttl
                old = self._data.get(key)
                if old is None:
                    self._data[key] = (expire, [rec])
                else:
                    old_expire, old_recs = old
                    # 同名同类型合并成一组，整体取最晚的过期时间
                    merged = [r for r in old_recs if r.rdata != rec.rdata]
                    merged.append(rec)
                    self._data[key] = (max(old_expire, expire), merged)

    def __len__(self):
        with self._lock:
            return len(self._data)
