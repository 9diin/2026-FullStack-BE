from collections import deque
from threading import Lock
from time import monotonic


class AnonymousGenerationRateLimiter:
    def __init__(self, limit: int = 5, window_seconds: int = 3600) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._requests: dict[str, deque[float]] = {}
        self._lock = Lock()

    def allow(self, client_id: str) -> bool:
        now = monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            timestamps = self._requests.setdefault(client_id, deque())
            while timestamps and timestamps[0] <= cutoff:
                timestamps.popleft()
            if len(timestamps) >= self.limit:
                return False
            timestamps.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._requests.clear()


anonymous_generation_rate_limiter = AnonymousGenerationRateLimiter()
