"""In-process sliding-window rate limiter (docs/ARCHITECTURE.md §5.2).

Deliberately small and dependency-free. Counters live in this process's memory,
so with N uvicorn workers the effective limit is up to N times the configured value
and every deploy resets it. That is the documented pilot trade-off; a shared
store (database table or Redis) is the upgrade path if abuse appears.

Keys are opaque strings chosen by the caller, e.g. `login:ip:203.0.113.9` or
`login:id:+254700000001`. The limiter never knows whether an identifier exists,
so its answers cannot leak that either.
"""

import time
from collections import deque
from collections.abc import Callable

# Drop empty buckets once the table grows past this many keys, so a scan of many
# distinct IPs cannot grow memory without bound.
_SWEEP_THRESHOLD = 10_000


class RateLimiter:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}

    def hit(self, key: str, *, limit: int, window_seconds: float = 60.0) -> float | None:
        """Record one attempt for `key`.

        Returns None when the attempt is within `limit` per `window_seconds`, else the
        number of seconds until the oldest counted attempt leaves the window. The
        rejected attempt is not counted, so a blocked client is not blocked for longer
        by continuing to retry.
        """
        now = self._clock()
        bucket = self._hits.get(key)
        if bucket is None:
            bucket = deque()
            self._hits[key] = bucket
        cutoff = now - window_seconds
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if len(bucket) >= limit:
            return max(bucket[0] + window_seconds - now, 0.0)
        bucket.append(now)
        if len(self._hits) > _SWEEP_THRESHOLD:
            self._sweep(cutoff)
        return None

    def reset(self) -> None:
        self._hits.clear()

    def _sweep(self, cutoff: float) -> None:
        stale = [key for key, bucket in self._hits.items() if not bucket or bucket[-1] <= cutoff]
        for key in stale:
            del self._hits[key]
