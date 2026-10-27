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

    def __init__(self, max_requests: int = 30, window_seconds: float = 60.0, max_keys: int = 5000) -> None:
        self._max = max_requests
        self._window = window_seconds
        self._max_keys = max_keys
        self._lock = threading.Lock()
        self._hits: dict[str, list[float]] = defaultdict(list)

    def allow(self, key: str) -> bool:
        if self._max <= 0:
            return True
        now = time.monotonic()
        cutoff = now - self._window
        with self._lock:
            if key not in self._hits and len(self._hits) >= self._max_keys:
                self._prune_stale(cutoff)

            timestamps = self._hits[key]
            # Prune expired timestamps
            valid = [t for t in timestamps if t > cutoff]
            if len(valid) >= self._max:
                self._hits[key] = valid
                return False
            valid.append(now)
            self._hits[key] = valid
            return True

    def _prune_stale(self, cutoff: float) -> None:
        stale = [k for k, v in self._hits.items() if not v or v[-1] <= cutoff]
        for k in stale:
            del self._hits[k]
        if len(self._hits) > self._max_keys:
            sorted_keys = sorted(
                self._hits.keys(),
                key=lambda k: self._hits[k][-1] if self._hits[k] else 0,
            )
            for k in sorted_keys[: len(self._hits) - self._max_keys]:
                del self._hits[k]

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
