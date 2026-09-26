"""A small thread-safe LRU cache that computes each key once, even under concurrent requests.

FastAPI runs sync handlers on threadpool threads, and the web client sends parallel requests for
the same timestep; a plain functools.lru_cache would let every concurrent miss compute. Here the
first caller computes while the others wait for its result. Failures are not cached.
"""

import threading
from collections import OrderedDict
from collections.abc import Callable, Hashable


class SingleFlightLRU[K: Hashable, V]:
    def __init__(self, compute: Callable[..., V], maxsize: int = 8) -> None:
        self.compute = compute  # called as compute(*key); replaceable (tests count calls)
        self.maxsize = maxsize
        self._cache: OrderedDict[K, V] = OrderedDict()
        self._lock = threading.Lock()
        self._key_locks: dict[K, threading.Lock] = {}

    def get(self, key: K) -> V:
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
            key_lock = self._key_locks.setdefault(key, threading.Lock())
        with key_lock:
            with self._lock:  # another thread may have finished it while we waited
                if key in self._cache:
                    self._cache.move_to_end(key)
                    return self._cache[key]
            try:
                value = self.compute(*key) if isinstance(key, tuple) else self.compute(key)
            finally:
                with self._lock:
                    self._key_locks.pop(key, None)
            with self._lock:
                self._cache[key] = value
                while len(self._cache) > self.maxsize:
                    self._cache.popitem(last=False)
            return value

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
