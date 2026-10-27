"""Sliding-window in-memory rate limiter keyed by client identifier."""

from __future__ import annotations

import threading
import time
from collections import defaultdict


class RateLimiter:
    """Per-client sliding-window counter.

    `max_requests` requests are allowed per `window_seconds` window.
    Thread-safe.
    """

    def __init__(self, max_requests: int = 30, window_seconds: float = 60.0) -> None:
        self._max = max_requests
        self._window = window_seconds
        self._lock = threading.Lock()
        self._hits: dict[str, list[float]] = defaultdict(list)

    def allow(self, key: str) -> bool:
        if self._max <= 0:
            return True
        now = time.monotonic()
        cutoff = now - self._window
        with self._lock:
            timestamps = self._hits[key]
            # Prune expired timestamps
            valid = [t for t in timestamps if t > cutoff]
            if len(valid) >= self._max:
                self._hits[key] = valid
                return False
            valid.append(now)
            self._hits[key] = valid
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
