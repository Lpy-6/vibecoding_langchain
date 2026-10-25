"""
In-process sliding-window rate limiter. Good enough for a single-node local
deployment; the interface can be swapped for Redis in a multi-node setup.
"""
from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque

from fastapi import HTTPException, status


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def hit(self, key: str, limit: int, window_seconds: int = 60) -> None:
        if limit <= 0:
            return
        now = time.monotonic()
        async with self._lock:
            bucket = self._events[key]
            cutoff = now - window_seconds
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                retry_after = max(1, int(window_seconds - (now - bucket[0])))
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"请求过于频繁，请 {retry_after} 秒后再试",
                    headers={"Retry-After": str(retry_after)},
                )
            bucket.append(now)
            if len(self._events) > 10000:
                for k in [k for k, v in self._events.items() if not v]:
                    self._events.pop(k, None)


limiter = SlidingWindowLimiter()
