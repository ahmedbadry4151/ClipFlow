"""Lightweight circuit breaker for external service calls."""

from __future__ import annotations

import threading
import time


class CircuitBreaker:
    """Three-state breaker: CLOSED -> OPEN -> HALF_OPEN -> CLOSED.

    - CLOSED: requests pass through normally.
    - OPEN: requests fail immediately (no call to the external service).
    - HALF_OPEN: one probe request is allowed; success closes, failure re-opens.
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        half_open_max: int = 1,
    ) -> None:
        self._threshold = failure_threshold
        self._recovery = recovery_timeout
        self._half_open_max = half_open_max
        self._lock = threading.Lock()
        self._failures = 0
        self._half_open_count = 0
        self._state = self.CLOSED
        self._opened_at = 0.0

    @property
    def state(self) -> str:
        with self._lock:
            if self._state == self.OPEN:
                if time.monotonic() - self._opened_at >= self._recovery:
                    self._state = self.HALF_OPEN
                    self._half_open_count = 0
            return self._state

    def allow_request(self) -> bool:
        """Return True if the request should proceed."""
        with self._lock:
            if self._state == self.OPEN:
                if time.monotonic() - self._opened_at >= self._recovery:
                    self._state = self.HALF_OPEN
                    self._half_open_count = 0
            if self._state == self.CLOSED:
                return True
            if self._state == self.HALF_OPEN:
                if self._half_open_count < self._half_open_max:
                    self._half_open_count += 1
                    return True
                return False
            return False  # OPEN

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._half_open_count = 0
            self._state = self.CLOSED

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._state == self.HALF_OPEN or self._failures >= self._threshold:
                self._state = self.OPEN
                self._opened_at = time.monotonic()

    @property
    def is_open(self) -> bool:
        return self.state == self.OPEN
