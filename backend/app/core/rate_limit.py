import threading
import time

from app.core.errors import AppError


class RateLimiter:
    def __init__(self, limit: int, window_seconds: int):
        self.limit = limit
        self.window_seconds = window_seconds
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            recent = [stamp for stamp in self._hits.get(key, []) if now - stamp < self.window_seconds]
            if len(recent) >= self.limit:
                self._hits[key] = recent
                raise AppError(429, "rate_limited", "Too many attempts. Try again later.")
            recent.append(now)
            self._hits[key] = recent
