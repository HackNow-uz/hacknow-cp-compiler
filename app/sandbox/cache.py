import hashlib
import shutil
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field


@dataclass
class _CacheEntry:
    """Compiled artifacts directory + metadata."""
    cache_dir: str
    compile_output: str
    compile_time_ms: int
    created_at: float = field(default_factory=time.time)
    ref_count: int = 0


class _CompileCache:
    """
    LRU compilation cache keyed by (language_id, sha256(source_code)).

    Reuses previous compilation results via hardlinks during contests
    and rejudges, reducing compile time from 500ms-10s to 0ms.
    """

    def __init__(self, max_entries: int, ttl_seconds: int):
        self._max = max_entries
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._entries: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._hits = 0
        self._misses = 0

    @staticmethod
    def _key(language_id: str, source_code: str) -> str:
        h = hashlib.sha256(source_code.encode("utf-8")).hexdigest()
        return f"{language_id}:{h}"

    def get(self, language_id: str, source_code: str) -> _CacheEntry | None:
        if self._max <= 0:
            return None
        key = self._key(language_id, source_code)
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self._misses += 1
                return None
            if time.time() - entry.created_at > self._ttl:
                self._entries.pop(key, None)
                if entry.ref_count <= 0:
                    shutil.rmtree(entry.cache_dir, ignore_errors=True)
                self._misses += 1
                return None
            self._entries.move_to_end(key)
            entry.ref_count += 1
            self._hits += 1
            return entry

    def put(
        self,
        language_id: str,
        source_code: str,
        cache_dir: str,
        compile_output: str,
        compile_time_ms: int,
    ) -> _CacheEntry:
        if self._max <= 0:
            return _CacheEntry(cache_dir, compile_output, compile_time_ms, ref_count=1)
        key = self._key(language_id, source_code)
        entry = _CacheEntry(cache_dir, compile_output, compile_time_ms, ref_count=1)
        with self._lock:
            old = self._entries.pop(key, None)
            if old and old.ref_count <= 0:
                shutil.rmtree(old.cache_dir, ignore_errors=True)
            self._entries[key] = entry
            while len(self._entries) > self._max:
                _, evicted = self._entries.popitem(last=False)
                if evicted.ref_count <= 0:
                    shutil.rmtree(evicted.cache_dir, ignore_errors=True)
        return entry

    def release(self, language_id: str, source_code: str) -> None:
        """Dec ref_count when caller is done with compiled artifacts."""
        if self._max <= 0:
            return
        key = self._key(language_id, source_code)
        with self._lock:
            entry = self._entries.get(key)
            if entry:
                entry.ref_count = max(0, entry.ref_count - 1)

    @property
    def stats(self) -> dict:
        with self._lock:
            return {
                "size": len(self._entries),
                "max": self._max,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": (
                    round(self._hits / (self._hits + self._misses), 3)
                    if (self._hits + self._misses) > 0 else 0.0
                ),
            }
