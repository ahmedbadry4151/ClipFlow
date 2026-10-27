from __future__ import annotations
import threading
import time
import pytest
from app.ratelimit import RateLimiter


def test_ratelimit_allows_up_to_max():
    limiter = RateLimiter(max_requests=3, window_seconds=0.2)
    assert limiter.allow("ip1") is True
    assert limiter.allow("ip1") is True
    assert limiter.allow("ip1") is True
    assert limiter.allow("ip1") is False


def test_ratelimit_tracks_per_client():
    limiter = RateLimiter(max_requests=2, window_seconds=0.2)
    assert limiter.allow("ip1") is True
    assert limiter.allow("ip1") is True
    assert limiter.allow("ip1") is False

    # ip2 is unaffected
    assert limiter.allow("ip2") is True
    assert limiter.allow("ip2") is True
    assert limiter.allow("ip2") is False


def test_ratelimit_sliding_window_expiry():
    limiter = RateLimiter(max_requests=2, window_seconds=0.08)
    assert limiter.allow("ip1") is True
    assert limiter.allow("ip1") is True
    assert limiter.allow("ip1") is False

    # Wait for window to expire
    time.sleep(0.09)
    assert limiter.allow("ip1") is True


def test_ratelimit_reset():
    limiter = RateLimiter(max_requests=2, window_seconds=10.0)
    assert limiter.allow("ip1") is True
    assert limiter.allow("ip1") is True
    assert limiter.allow("ip1") is False

    limiter.reset()
    assert limiter.allow("ip1") is True


def test_ratelimit_disabled():
    limiter = RateLimiter(max_requests=0, window_seconds=10.0)
    for _ in range(20):
        assert limiter.allow("ip1") is True


def test_ratelimit_concurrency():
    limiter = RateLimiter(max_requests=50, window_seconds=1.0)
    allowed_count = 0
    lock = threading.Lock()

    def hit():
        nonlocal allowed_count
        if limiter.allow("shared-ip"):
            with lock:
                allowed_count += 1

    threads = [threading.Thread(target=hit) for _ in range(100)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert allowed_count == 50


def test_ratelimit_prune_stale_keys():
    limiter = RateLimiter(max_requests=5, window_seconds=0.05, max_keys=3)
    # Fill up 3 keys
    limiter.allow("ip1")
    limiter.allow("ip2")
    limiter.allow("ip3")
    assert len(limiter._hits) == 3

    # Wait for timestamps to become stale
    time.sleep(0.06)

    # 4th key triggers pruning of expired keys
    limiter.allow("ip4")
    # Expired keys should be purged, keeping memory bounded
    assert len(limiter._hits) <= 3
    assert "ip4" in limiter._hits
