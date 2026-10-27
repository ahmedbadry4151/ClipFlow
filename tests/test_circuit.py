from __future__ import annotations
import time
import pytest
from app.circuit import CircuitBreaker


def test_circuit_initial_state():
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout=0.1)
    assert cb.state == CircuitBreaker.CLOSED
    assert not cb.is_open
    assert cb.allow_request() is True


def test_circuit_trips_to_open_after_threshold():
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout=0.1)
    cb.record_failure()
    assert cb.state == CircuitBreaker.CLOSED
    assert cb.allow_request() is True

    cb.record_failure()
    assert cb.state == CircuitBreaker.CLOSED

    cb.record_failure()
    assert cb.state == CircuitBreaker.OPEN
    assert cb.is_open is True
    assert cb.allow_request() is False


def test_circuit_success_resets_failures():
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout=0.1)
    cb.record_failure()
    cb.record_failure()
    cb.record_success()
    assert cb.state == CircuitBreaker.CLOSED

    # Should take 3 more failures to trip
    cb.record_failure()
    cb.record_failure()
    assert cb.state == CircuitBreaker.CLOSED
    cb.record_failure()
    assert cb.state == CircuitBreaker.OPEN


def test_circuit_recovers_to_half_open_and_closes_on_success():
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.05, half_open_max=1)
    cb.record_failure()
    cb.record_failure()
    assert cb.state == CircuitBreaker.OPEN

    # Wait for recovery timeout
    time.sleep(0.06)
    assert cb.state == CircuitBreaker.HALF_OPEN

    # Exactly 1 request allowed
    assert cb.allow_request() is True
    # Next request rejected until resolved
    assert cb.allow_request() is False

    # Probe succeeds -> CLOSED
    cb.record_success()
    assert cb.state == CircuitBreaker.CLOSED
    assert cb.allow_request() is True


def test_circuit_half_open_reopens_on_failure():
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.05, half_open_max=1)
    cb.record_failure()
    cb.record_failure()
    assert cb.state == CircuitBreaker.OPEN

    time.sleep(0.06)
    assert cb.state == CircuitBreaker.HALF_OPEN
    assert cb.allow_request() is True

    # Probe fails -> OPEN again immediately
    cb.record_failure()
    assert cb.state == CircuitBreaker.OPEN
    assert cb.allow_request() is False
