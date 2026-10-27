import time
from app.circuit import CircuitBreaker
from app.ratelimit import RateLimiter


def test_circuit_breaker_transitions():
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1)
    assert cb.state == CircuitBreaker.CLOSED
    assert cb.allow_request() is True

    # 1 failure - still closed
    cb.record_failure()
    assert cb.state == CircuitBreaker.CLOSED
    assert cb.allow_request() is True

    # 2 failures - trips open
    cb.record_failure()
    assert cb.state == CircuitBreaker.OPEN
    assert cb.allow_request() is False

    # Wait for recovery timeout -> half-open
    time.sleep(0.12)
    assert cb.state == CircuitBreaker.HALF_OPEN
    assert cb.allow_request() is True
    # Half-open only permits 1 probe request
    assert cb.allow_request() is False

    # Success closes breaker
    cb.record_success()
    assert cb.state == CircuitBreaker.CLOSED
    assert cb.allow_request() is True


def test_circuit_breaker_half_open_failure():
    cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.05)
    cb.record_failure()
    assert cb.state == CircuitBreaker.OPEN
    time.sleep(0.06)
    assert cb.state == CircuitBreaker.HALF_OPEN

    # Failure in half-open re-trips open immediately
    cb.record_failure()
    assert cb.state == CircuitBreaker.OPEN


def test_rate_limiter():
    limiter = RateLimiter(max_requests=3, window_seconds=0.2)
    ip = "192.168.1.100"

    assert limiter.allow(ip) is True
    assert limiter.allow(ip) is True
    assert limiter.allow(ip) is True
    # 4th exceeds max_requests
    assert limiter.allow(ip) is False

    # Different key allowed independently
    assert limiter.allow("10.0.0.1") is True

    # Window expiry
    time.sleep(0.22)
    assert limiter.allow(ip) is True
