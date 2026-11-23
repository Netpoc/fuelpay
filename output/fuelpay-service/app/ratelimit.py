"""A minimal in-process sliding-window rate limiter.

Enough to blunt code guessing at the one public endpoint, `/v1/demo/redeem`.
State is per process and lost on restart, so behind several replicas the
effective limit multiplies; coupon redemption caps remain the real control.
"""

import time
from collections import deque
from collections.abc import Callable


class SlidingWindowLimiter:
    def __init__(
        self, limit: int, window_seconds: float, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.limit = limit
        self.window = window_seconds
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}

    def allow(self, key: str) -> bool:
        """Record an attempt for `key`; False if it exceeds the limit."""
        now = self._clock()
        hits = self._hits.setdefault(key, deque())
        while hits and now - hits[0] >= self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        # Drop idle keys now and then so the map cannot grow without bound.
        if len(self._hits) > 10_000:
            self._hits = {k: v for k, v in self._hits.items() if v and now - v[-1] < self.window}
        return True
