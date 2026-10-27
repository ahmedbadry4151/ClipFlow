from __future__ import annotations
import time
from pathlib import Path
import pytest
from app.events import EventBus
from app.manager import JobManager, _Watchdog, ItemState, JobState
from app.models import DownloadOptions
from app.store import Store


def test_watchdog_cancels_stale_active_item(settings):
    settings.download_timeout = 1  # 1 second timeout
    store = Store(settings.data_path / "watchdog.db")
    manager = JobManager(settings, store, EventBus())
    try:
        now = time.time()
        item = ItemState(
            id="stale1",
            job_id="job1",
            index=1,
            url="https://example.com/v",
            title="Stale Video",
            created_at=now - 10,
            status="running",
            attempts=1,
            updated_at=now - 5,  # 5 seconds ago > 1s timeout
        )
        job = JobState(
            id="job1",
            url="https://example.com/v",
            title="Job 1",
            kind="video",
            options=DownloadOptions(),
            created_at=now - 10,
            items=[item],
            status="running",
        )
        with manager._lock:
            manager._jobs["job1"] = job

        assert not item.cancel.is_set()

        # Run watchdog with short interval
        wd = _Watchdog(manager, interval=0.05)
        wd.start()
        time.sleep(0.15)
        wd.stop()

        assert item.cancel.is_set()
    finally:
        manager.shutdown()
        store.close()


def test_watchdog_ignores_completed_or_not_started_items(settings):
    settings.download_timeout = 1
    store = Store(settings.data_path / "watchdog2.db")
    manager = JobManager(settings, store, EventBus())
    try:
        now = time.time()
        # Item that finished
        completed_item = ItemState(
            id="comp1",
            job_id="job2",
            index=1,
            url="https://example.com/c",
            title="Completed Video",
            created_at=now - 10,
            status="completed",
            attempts=1,
            updated_at=now - 5,
        )
        # Item that is queued but attempts == 0
        queued_item = ItemState(
            id="q1",
            job_id="job2",
            index=2,
            url="https://example.com/q",
            title="Queued Video",
            created_at=now - 10,
            status="queued",
            attempts=0,
            updated_at=now - 5,
        )
        job = JobState(
            id="job2",
            url="https://example.com/v2",
            title="Job 2",
            kind="video",
            options=DownloadOptions(),
            created_at=now - 10,
            items=[completed_item, queued_item],
            status="running",
        )
        with manager._lock:
            manager._jobs["job2"] = job

        wd = _Watchdog(manager, interval=0.05)
        wd.start()
        time.sleep(0.15)
        wd.stop()

        assert not completed_item.cancel.is_set()
        assert not queued_item.cancel.is_set()
    finally:
        manager.shutdown()
        store.close()


def test_watchdog_disabled_when_zero(settings):
    settings.download_timeout = 0
    store = Store(settings.data_path / "watchdog3.db")
    manager = JobManager(settings, store, EventBus())
    try:
        now = time.time()
        item = ItemState(
            id="stale2",
            job_id="job3",
            index=1,
            url="https://example.com/v3",
            title="Stale Video",
            created_at=now - 10,
            status="running",
            attempts=1,
            updated_at=now - 5,
        )
        job = JobState(
            id="job3",
            url="https://example.com/v3",
            title="Job 3",
            kind="video",
            options=DownloadOptions(),
            created_at=now - 10,
            items=[item],
            status="running",
        )
        with manager._lock:
            manager._jobs["job3"] = job

        wd = _Watchdog(manager, interval=0.05)
        wd.start()
        time.sleep(0.15)
        wd.stop()

        assert not item.cancel.is_set()
    finally:
        manager.shutdown()
        store.close()
