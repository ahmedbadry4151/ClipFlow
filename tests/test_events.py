from __future__ import annotations

import asyncio
from typing import Any

from app.events import EventBus


class DirectLoop:
    """Synchronous event loop adapter for deterministic testing without socketpairs."""

    def is_closed(self) -> bool:
        return False

    def call_soon_threadsafe(self, callback: Any, *args: Any) -> None:
        callback(*args)


def test_event_bus_fanout():
    bus = EventBus()
    bus.attach_loop(DirectLoop())  # type: ignore
    first = bus.subscribe()
    second = bus.subscribe()

    bus.publish({"type": "item", "n": 1})
    event_a = first.get_nowait()
    event_b = second.get_nowait()
    assert event_a == {"type": "item", "n": 1}
    assert event_b == event_a

    bus.unsubscribe(first)
    bus.unsubscribe(second)
    assert bus._subscribers == set()


def test_event_bus_without_loop_is_noop():
    bus = EventBus()
    bus.publish({"type": "job"})  # must not raise


def test_event_bus_drops_oldest_when_full():
    bus = EventBus()
    bus.attach_loop(DirectLoop())  # type: ignore
    queue = bus.subscribe()
    for index in range(queue.maxsize + 5):
        bus.publish({"n": index})
    assert queue.qsize() == queue.maxsize
    assert queue.get_nowait()["n"] == 5
