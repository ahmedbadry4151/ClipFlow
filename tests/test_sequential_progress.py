from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import pytest

from app import manager as manager_module
from app.config import Settings
from yt_dlp.utils import DownloadCancelled
from app.events import EventBus
from app.manager import JobManager
from app.models import DownloadOptions, SelectedEntry
from app.store import Store
from tests.helpers import wait_for


class DirectLoop:
    """Synchronous event loop adapter for deterministic testing without socketpairs."""

    def is_closed(self) -> bool:
        return False

    def call_soon_threadsafe(self, callback: Any, *args: Any) -> None:
        callback(*args)


def _entry(video_id: str, index: int) -> SelectedEntry:
    return SelectedEntry(
        url=f"https://www.youtube.com/watch?v={video_id}",
        title=f"Video {video_id}",
        index=index,
        duration=60.0,
    )


# ---------------------------------------------------------------------------
# Test 1: A playlist with 5 videos completing one by one (sequential)
# ---------------------------------------------------------------------------
def test_playlist_5_videos_complete_one_by_one(tmp_path: Path, monkeypatch):
    settings = Settings(
        download_dir=tmp_path / "downloads",
        data_dir=tmp_path / "data",
        max_concurrent_downloads=1,
        retries=0,
    )
    settings.prepare_dirs()
    store = Store(settings.data_path / "test.db")
    bus = EventBus()
    bus.attach_loop(DirectLoop())  # type: ignore
    manager = JobManager(settings, store, bus)

    events_queue = bus.subscribe()
    completed_order: list[str] = []

    def fake_download(url, options, settings_arg, **kwargs):
        vid = url.split("=")[-1]
        hook = kwargs.get("progress_hook")
        if hook:
            hook({
                "status": "downloading",
                "downloaded_bytes": 500,
                "total_bytes": 1000,
                "speed": 100,
                "eta": 5,
                "info_dict": {"format_id": "v"},
            })
        time.sleep(0.05)
        path = settings_arg.download_path / f"{vid}.mp4"
        path.write_bytes(b"content")
        completed_order.append(vid)
        return {"id": vid, "filepath": str(path)}

    monkeypatch.setattr(manager_module, "run_download", fake_download)

    try:
        entries = [_entry(f"v{i}", i) for i in range(1, 6)]
        job = manager.create_job(
            "https://www.youtube.com/playlist?list=PL_TEST",
            DownloadOptions(mode="playlist"),
            entries=entries,
            title="Playlist 5",
        )

        assert wait_for(lambda: manager.get_job(job.id).status == "completed", timeout=10)
        assert completed_order == ["v1", "v2", "v3", "v4", "v5"]

        final_job = manager.get_job(job.id)
        assert final_job is not None
        summary = final_job.summary()
        assert summary["total_items"] == 5
        assert summary["completed_items"] == 5
        assert summary["failed_items"] == 0
        assert summary["cancelled_items"] == 0
        assert summary["active_items"] == 0
        assert summary["queued_items"] == 0
        assert summary["percent"] == 100.0

        for item in final_job.items:
            assert item.status == "completed"
            assert item.percent == 100.0

        # Drain and inspect event stream
        received_events: list[dict[str, Any]] = []
        while not events_queue.empty():
            received_events.append(events_queue.get_nowait())

        event_types = [e.get("type") for e in received_events]
        assert "queue_updated" in event_types
        assert "video_started" in event_types
        assert "video_progress" in event_types
        assert "video_completed" in event_types

        # Verify exactly 5 video_completed events (one per video)
        completed_events = [e for e in received_events if e.get("type") == "video_completed"]
        assert len(completed_events) == 5
        assert [e["video_id"] for e in completed_events] == [item.id for item in final_job.items]

    finally:
        manager.shutdown()
        store.close()


# ---------------------------------------------------------------------------
# Test 2: Real-time progress updates during an active download
# ---------------------------------------------------------------------------
def test_real_time_progress_updates_during_download(tmp_path: Path, monkeypatch):
    settings = Settings(
        download_dir=tmp_path / "downloads",
        data_dir=tmp_path / "data",
        max_concurrent_downloads=1,
    )
    settings.prepare_dirs()
    store = Store(settings.data_path / "test.db")
    bus = EventBus()
    bus.attach_loop(DirectLoop())  # type: ignore
    manager = JobManager(settings, store, bus)
    events_queue = bus.subscribe()

    progress_milestones: list[float] = []

    def fake_download(url, options, settings_arg, **kwargs):
        vid = url.split("=")[-1]
        hook = kwargs.get("progress_hook")
        pp_hook = kwargs.get("pp_hook")

        for downloaded, total in [(100, 1000), (500, 1000), (900, 1000)]:
            time.sleep(0.26)  # Exceed 0.25s last_emit throttle
            if hook:
                hook({
                    "status": "downloading",
                    "downloaded_bytes": downloaded,
                    "total_bytes": total,
                    "speed": 500,
                    "eta": 1,
                    "info_dict": {"format_id": "v"},
                })

        time.sleep(0.26)
        if pp_hook:
            pp_hook({"status": "processing"})

        path = settings_arg.download_path / f"{vid}.mp4"
        path.write_bytes(b"content")
        return {"id": vid, "filepath": str(path)}

    monkeypatch.setattr(manager_module, "run_download", fake_download)

    try:
        job = manager.create_job(
            "https://www.youtube.com/watch?v=realtime1",
            DownloadOptions(),
            entries=[_entry("realtime1", 1)],
        )

        assert wait_for(lambda: manager.get_job(job.id).status == "completed", timeout=10)

        received_events: list[dict[str, Any]] = []
        while not events_queue.empty():
            received_events.append(events_queue.get_nowait())

        prog_events = [e for e in received_events if e.get("type") == "video_progress"]
        assert len(prog_events) >= 3

        percents = [e["percent"] for e in prog_events if e.get("status") == "downloading"]
        # Percents must be strictly non-decreasing
        assert percents == sorted(percents)
        assert 10.0 in percents
        assert 50.0 in percents
        assert 90.0 in percents

        # Postprocessing event
        processing_events = [e for e in prog_events if e.get("status") == "processing"]
        assert len(processing_events) >= 1

        # Final completion event
        comp_events = [e for e in received_events if e.get("type") == "video_completed"]
        assert len(comp_events) == 1
        assert comp_events[0]["percent"] == 100.0

    finally:
        manager.shutdown()
        store.close()


# ---------------------------------------------------------------------------
# Test 3: One video failing while other videos continue
# ---------------------------------------------------------------------------
def test_one_video_fails_while_others_continue(tmp_path: Path, monkeypatch):
    settings = Settings(
        download_dir=tmp_path / "downloads",
        data_dir=tmp_path / "data",
        max_concurrent_downloads=1,
        retries=0,
    )
    settings.prepare_dirs()
    store = Store(settings.data_path / "test.db")
    bus = EventBus()
    bus.attach_loop(DirectLoop())  # type: ignore
    manager = JobManager(settings, store, bus)
    events_queue = bus.subscribe()

    def fake_download(url, options, settings_arg, **kwargs):
        vid = url.split("=")[-1]
        if vid == "fail2":
            raise RuntimeError("Private video - Sign in to confirm you are not a bot")
        path = settings_arg.download_path / f"{vid}.mp4"
        path.write_bytes(b"content")
        return {"id": vid, "filepath": str(path)}

    monkeypatch.setattr(manager_module, "run_download", fake_download)

    try:
        entries = [_entry("ok1", 1), _entry("fail2", 2), _entry("ok3", 3)]
        job = manager.create_job(
            "https://www.youtube.com/playlist?list=PL_FAIL",
            DownloadOptions(mode="playlist"),
            entries=entries,
        )

        assert wait_for(lambda: manager.get_job(job.id).status == "partial", timeout=10)

        final_job = manager.get_job(job.id)
        assert final_job is not None
        summary = final_job.summary()

        assert summary["total_items"] == 3
        assert summary["completed_items"] == 2
        assert summary["failed_items"] == 1
        assert summary["cancelled_items"] == 0
        assert summary["active_items"] == 0
        assert summary["queued_items"] == 0
        # 2 of 3 completed = ~66.7%
        assert summary["percent"] == pytest.approx(66.7, abs=0.2)

        items_by_url = {item.url: item for item in final_job.items}
        assert items_by_url["https://www.youtube.com/watch?v=ok1"].status == "completed"
        assert items_by_url["https://www.youtube.com/watch?v=fail2"].status == "failed"
        assert items_by_url["https://www.youtube.com/watch?v=ok3"].status == "completed"

        received_events: list[dict[str, Any]] = []
        while not events_queue.empty():
            received_events.append(events_queue.get_nowait())

        failed_events = [e for e in received_events if e.get("type") == "video_failed"]
        assert len(failed_events) == 1
        assert failed_events[0]["video_id"] == items_by_url["https://www.youtube.com/watch?v=fail2"].id

    finally:
        manager.shutdown()
        store.close()


# ---------------------------------------------------------------------------
# Test 4: Cancellation of an individual video
# ---------------------------------------------------------------------------
def test_cancellation_of_individual_video(tmp_path: Path, monkeypatch):
    settings = Settings(
        download_dir=tmp_path / "downloads",
        data_dir=tmp_path / "data",
        max_concurrent_downloads=1,
    )
    settings.prepare_dirs()
    store = Store(settings.data_path / "test.db")
    bus = EventBus()
    bus.attach_loop(DirectLoop())  # type: ignore
    manager = JobManager(settings, store, bus)
    events_queue = bus.subscribe()

    step_event = threading.Event()

    def fake_download(url, options, settings_arg, **kwargs):
        vid = url.split("=")[-1]
        cancel_event = kwargs.get("cancel_event")
        if vid == "c1":
            step_event.set()  # Let test know v1 is running
            time.sleep(0.1)
        path = settings_arg.download_path / f"{vid}.mp4"
        path.write_bytes(b"content")
        return {"id": vid, "filepath": str(path)}

    monkeypatch.setattr(manager_module, "run_download", fake_download)

    try:
        entries = [_entry("c1", 1), _entry("c2", 2), _entry("c3", 3)]
        job = manager.create_job(
            "https://www.youtube.com/playlist?list=PL_CANCEL",
            DownloadOptions(mode="playlist"),
            entries=entries,
        )

        assert step_event.wait(5.0)
        # Cancel item c2 while it is queued
        item2 = job.items[1]
        assert item2.url.endswith("=c2")
        manager.cancel_item(job.id, item2.id)

        assert wait_for(lambda: manager.get_job(job.id).status == "partial", timeout=10)

        final_job = manager.get_job(job.id)
        assert final_job is not None
        summary = final_job.summary()

        assert summary["completed_items"] == 2
        assert summary["cancelled_items"] == 1
        assert summary["failed_items"] == 0
        assert summary["percent"] == pytest.approx(66.7, abs=0.2)
        assert final_job.items[1].status == "cancelled"

        received_events: list[dict[str, Any]] = []
        while not events_queue.empty():
            received_events.append(events_queue.get_nowait())

        cancelled_events = [e for e in received_events if e.get("type") == "video_cancelled"]
        assert len(cancelled_events) == 1
        assert cancelled_events[0]["video_id"] == item2.id

    finally:
        manager.shutdown()
        store.close()


# ---------------------------------------------------------------------------
# Test 5: Multiple concurrent downloads
# ---------------------------------------------------------------------------
def test_multiple_concurrent_downloads(tmp_path: Path, monkeypatch):
    settings = Settings(
        download_dir=tmp_path / "downloads",
        data_dir=tmp_path / "data",
        max_concurrent_downloads=3,
    )
    settings.prepare_dirs()
    store = Store(settings.data_path / "test.db")
    bus = EventBus()
    bus.attach_loop(DirectLoop())  # type: ignore
    manager = JobManager(settings, store, bus)

    active_count = 0
    max_observed_active = 0
    active_lock = threading.Lock()
    barrier = threading.Barrier(3)

    def fake_download(url, options, settings_arg, **kwargs):
        nonlocal active_count, max_observed_active
        vid = url.split("=")[-1]
        with active_lock:
            active_count += 1
            if active_count > max_observed_active:
                max_observed_active = active_count

        if vid in {"par1", "par2", "par3"}:
            barrier.wait(timeout=5.0)

        time.sleep(0.05)
        with active_lock:
            active_count -= 1

        path = settings_arg.download_path / f"{vid}.mp4"
        path.write_bytes(b"content")
        return {"id": vid, "filepath": str(path)}

    monkeypatch.setattr(manager_module, "run_download", fake_download)

    try:
        entries = [_entry(f"par{i}", i) for i in range(1, 6)]
        job = manager.create_job(
            "https://www.youtube.com/playlist?list=PL_PAR",
            DownloadOptions(mode="playlist"),
            entries=entries,
        )

        assert wait_for(lambda: manager.get_job(job.id).status == "completed", timeout=10)
        assert max_observed_active == 3
        summary = manager.get_job(job.id).summary()
        assert summary["completed_items"] == 5
        assert summary["percent"] == 100.0

    finally:
        manager.shutdown()
        store.close()


# ---------------------------------------------------------------------------
# Test 6: SSE reconnection and duplicate-event prevention
# ---------------------------------------------------------------------------
def test_sse_reconnection_and_duplicate_event_prevention(tmp_path: Path, monkeypatch):
    settings = Settings(
        download_dir=tmp_path / "downloads",
        data_dir=tmp_path / "data",
        max_concurrent_downloads=1,
    )
    settings.prepare_dirs()
    store = Store(settings.data_path / "test.db")
    bus = EventBus()
    bus.attach_loop(DirectLoop())  # type: ignore
    manager = JobManager(settings, store, bus)

    sub1 = bus.subscribe()
    step_rec1 = threading.Event()
    cont_rec1 = threading.Event()
    gate_rec2 = threading.Event()

    def fake_download(url, options, settings_arg, **kwargs):
        vid = url.split("=")[-1]
        path = settings_arg.download_path / f"{vid}.mp4"
        path.write_bytes(b"content")
        if vid == "rec1":
            step_rec1.set()
            assert cont_rec1.wait(timeout=5.0)
        elif vid == "rec2":
            assert gate_rec2.wait(timeout=5.0)
        return {"id": vid, "filepath": str(path)}

    monkeypatch.setattr(manager_module, "run_download", fake_download)

    try:
        entries = [_entry("rec1", 1), _entry("rec2", 2)]
        job = manager.create_job(
            "https://www.youtube.com/playlist?list=PL_REC",
            DownloadOptions(mode="playlist"),
            entries=entries,
        )

        # Wait for rec1 to finish
        assert step_rec1.wait(timeout=5.0)
        cont_rec1.set()
        assert wait_for(lambda: manager.get_job(job.id).items[0].status == "completed")

        # Simulate disconnect of client 1
        bus.unsubscribe(sub1)

        # Simulate reconnect of client 2 while rec2 is still downloading
        sub2 = bus.subscribe()
        snapshot = manager.snapshot(limit=10)
        assert len(snapshot) == 1
        assert snapshot[0]["completed_items"] == 1

        # Release rec2 to finish
        gate_rec2.set()

        # Let remaining video complete
        assert wait_for(lambda: manager.get_job(job.id).status == "completed", timeout=10)

        # Collect client 2's events
        sub2_events: list[dict[str, Any]] = []
        while not sub2.empty():
            sub2_events.append(sub2.get_nowait())

        # rec1 was completed before sub2 subscribed, so sub2 should NOT get duplicate rec1 completion
        rec1_completed = [
            e for e in sub2_events
            if e.get("type") == "video_completed" and e.get("video_id") == job.items[0].id
        ]
        assert len(rec1_completed) == 0

        # rec2 completion event was sent after sub2 subscribed
        rec2_completed = [
            e for e in sub2_events
            if e.get("type") == "video_completed" and e.get("video_id") == job.items[1].id
        ]
        assert len(rec2_completed) == 1

        bus.unsubscribe(sub2)

    finally:
        manager.shutdown()
        store.close()


# ---------------------------------------------------------------------------
# Test 7: Application restart and recovery of interrupted jobs
# ---------------------------------------------------------------------------
def test_application_restart_and_recovery_of_interrupted_jobs(tmp_path: Path, monkeypatch):
    settings = Settings(
        download_dir=tmp_path / "downloads",
        data_dir=tmp_path / "data",
        max_concurrent_downloads=1,
    )
    settings.prepare_dirs()
    db_path = settings.data_path / "restart.db"
    store1 = Store(db_path)
    bus1 = EventBus()
    bus1.attach_loop(DirectLoop())  # type: ignore

    def fake_download_1(url, options, settings_arg, **kwargs):
        vid = url.split("=")[-1]
        path = settings_arg.download_path / f"{vid}.mp4"
        path.write_bytes(b"content")
        return {"id": vid, "filepath": str(path)}

    monkeypatch.setattr(manager_module, "run_download", fake_download_1)

    manager1 = JobManager(settings, store1, bus1)
    entries = [_entry("rst1", 1), _entry("rst2", 2)]
    job = manager1.create_job(
        "https://www.youtube.com/playlist?list=PL_RST",
        DownloadOptions(mode="playlist"),
        entries=entries,
    )

    # Wait until job completes on first instance
    assert wait_for(lambda: manager1.get_job(job.id).status == "completed")
    manager1.shutdown()

    # Now simulate an interrupted item in the database (e.g. from crash during download)
    item2 = job.items[1]
    store1.save_items([{
        "id": item2.id,
        "job_id": job.id,
        "idx": item2.index,
        "url": item2.url,
        "title": item2.title,
        "duration": item2.duration,
        "status": "running",
        "percent": 45.0,
        "speed": 1000.0,
        "eta": 5.0,
        "downloaded": 450,
        "total": 1000,
        "filepath": "",
        "error": "",
        "attempts": 1,
        "created_at": item2.created_at,
        "updated_at": time.time(),
    }])
    store1.close()

    # Now spin up fresh server with new manager instance from same database
    store2 = Store(db_path)
    bus2 = EventBus()
    bus2.attach_loop(DirectLoop())  # type: ignore

    def fake_download_2(url, options, settings_arg, **kwargs):
        vid = url.split("=")[-1]
        path = settings_arg.download_path / f"{vid}.mp4"
        path.write_bytes(b"content")
        return {"id": vid, "filepath": str(path)}

    monkeypatch.setattr(manager_module, "run_download", fake_download_2)

    manager2 = JobManager(settings, store2, bus2)
    try:
        restored_job = manager2.get_job(job.id)
        assert restored_job is not None
        assert restored_job.items[0].status == "completed"
        # The interrupted item was restored as "interrupted"
        assert restored_job.items[1].status == "interrupted"
        assert restored_job.status in {"partial", "interrupted"}

        # Resume interrupted jobs
        resumed_count = manager2.resume_interrupted()
        assert resumed_count >= 1

        assert wait_for(lambda: manager2.get_job(job.id).status == "completed", timeout=10)
        final_summary = manager2.get_job(job.id).summary()
        assert final_summary["completed_items"] == 2
        assert final_summary["percent"] == 100.0

    finally:
        manager2.shutdown()
        store2.close()


# ---------------------------------------------------------------------------
# Test 8: Correct completed counters and final queue state
# ---------------------------------------------------------------------------
def test_correct_completed_counters_and_final_queue_state(tmp_path: Path):
    settings = Settings(
        download_dir=tmp_path / "downloads",
        data_dir=tmp_path / "data",
        max_concurrent_downloads=2,
    )
    settings.prepare_dirs()
    store = Store(settings.data_path / "test_counters.db")
    bus = EventBus()
    bus.attach_loop(DirectLoop())  # type: ignore
    manager = JobManager(settings, store, bus)

    try:
        entries = [_entry(f"cnt{i}", i) for i in range(1, 6)]
        job = manager.create_job(
            "https://www.youtube.com/playlist?list=PL_CNT",
            DownloadOptions(mode="playlist"),
            entries=entries,
        )

        # Manually verify counter calculation with various item states
        items = job.items
        items[0].status = "completed"
        items[0].percent = 100.0

        items[1].status = "completed"
        items[1].percent = 100.0

        items[2].status = "failed"
        items[2].error = "Network drop"

        items[3].status = "cancelled"
        items[3].error = "User cancelled"

        items[4].status = "interrupted"
        items[4].percent = 30.0

        summary = job.summary()
        assert summary["total_items"] == 5
        assert summary["completed_items"] == 2
        assert summary["failed_items"] == 1
        assert summary["cancelled_items"] == 1
        assert summary["interrupted_items"] == 1
        assert summary["active_items"] == 0
        assert summary["queued_items"] == 0

        # Percent should be (100 + 100 + 0 + 0 + 30) / 5 = 230 / 5 = 46.0%
        assert summary["percent"] == 46.0

    finally:
        manager.shutdown()
        store.close()


# ---------------------------------------------------------------------------
# Test 9: Unknown file sizes and fragmented downloads
# ---------------------------------------------------------------------------
def test_unknown_file_sizes_and_fragments(tmp_path: Path):
    settings = Settings(
        download_dir=tmp_path / "downloads",
        data_dir=tmp_path / "data",
    )
    settings.prepare_dirs()
    store = Store(settings.data_path / "test_fragments.db")
    bus = EventBus()
    bus.attach_loop(DirectLoop())  # type: ignore
    manager = JobManager(settings, store, bus)

    try:
        job = manager.create_job(
            "https://www.youtube.com/watch?v=frag1",
            DownloadOptions(),
            entries=[_entry("frag1", 1)],
        )
        item = job.items[0]

        # Scenario A: Unknown size, stream total is None
        data_unknown = {
            "status": "downloading",
            "downloaded_bytes": 10240,
            "total_bytes": None,
            "total_bytes_estimate": None,
            "speed": 1024,
            "eta": None,
            "info_dict": {"format_id": "frag_stream"},
        }
        manager._on_progress(item, data_unknown)
        assert item.downloaded == 10240
        assert item.total == 0
        assert item.percent == 0.0  # Indeterminate in UI, not fake 100%

        # Scenario B: Fragmented download with fragment_index and fragment_count
        data_fragment = {
            "status": "downloading",
            "downloaded_bytes": 50000,
            "total_bytes": None,
            "total_bytes_estimate": None,
            "fragment_index": 5,
            "fragment_count": 10,
            "speed": 2048,
            "eta": 5,
            "info_dict": {"format_id": "frag_stream"},
        }
        manager._on_progress(item, data_fragment)
        assert item.downloaded == 50000
        assert item.percent == 50.0  # 5 / 10 * 100

        # Scenario C: Stream finishes
        data_finish = {
            "status": "finished",
            "downloaded_bytes": 100000,
            "total_bytes": None,
            "info_dict": {"format_id": "frag_stream"},
        }
        manager._on_progress(item, data_finish)
        # 100% only once run_download completes successfully and sets completed status
        assert item.percent <= 99.9

    finally:
        manager.shutdown()
        store.close()


# ---------------------------------------------------------------------------
# Test 10: Active video cancellation during download and subsequent retry
# ---------------------------------------------------------------------------
def test_active_video_cancellation_and_retry(tmp_path: Path, monkeypatch):
    settings = Settings(
        download_dir=tmp_path / "downloads",
        data_dir=tmp_path / "data",
        max_concurrent_downloads=1,
    )
    settings.prepare_dirs()
    store = Store(settings.data_path / "test_active_cancel.db")
    bus = EventBus()
    bus.attach_loop(DirectLoop())  # type: ignore
    manager = JobManager(settings, store, bus)
    events_queue = bus.subscribe()

    active_step = threading.Event()
    cancelled_step = threading.Event()
    should_fail_first = True

    def fake_download(url, options, settings_arg, **kwargs):
        nonlocal should_fail_first
        vid = url.split("=")[-1]
        cancel_event = kwargs.get("cancel_event")
        if vid == "act1" and should_fail_first:
            active_step.set()
            # Wait for cancel_event to trigger
            assert cancel_event.wait(timeout=5.0)
            cancelled_step.set()
            raise DownloadCancelled("Cancelled by user")

        path = settings_arg.download_path / f"{vid}.mp4"
        path.write_bytes(b"content")
        return {"id": vid, "filepath": str(path)}

    monkeypatch.setattr(manager_module, "run_download", fake_download)

    try:
        entries = [_entry("act1", 1), _entry("act2", 2)]
        job = manager.create_job(
            "https://www.youtube.com/playlist?list=PL_ACT",
            DownloadOptions(mode="playlist"),
            entries=entries,
        )

        # Wait for act1 to start active downloading
        assert active_step.wait(timeout=5.0)
        item1 = job.items[0]

        # Cancel actively downloading item
        manager.cancel_item(job.id, item1.id)
        assert cancelled_step.wait(timeout=5.0)

        # Wait for job to reach partial state (act1 cancelled, act2 completed)
        assert wait_for(lambda: manager.get_job(job.id).status == "partial", timeout=10)

        summary = manager.get_job(job.id).summary()
        assert summary["completed_items"] == 1
        assert summary["cancelled_items"] == 1
        assert summary["total_items"] == 2
        assert manager.get_job(job.id).items[0].status == "cancelled"
        assert manager.get_job(job.id).items[1].status == "completed"

        # Drain events and verify act1 was cancelled with NO duplicate video_cancelled events
        received_events: list[dict[str, Any]] = []
        while not events_queue.empty():
            received_events.append(events_queue.get_nowait())

        cancelled_events = [
            e for e in received_events
            if e.get("type") == "video_cancelled" and e.get("video_id") == item1.id
        ]
        assert len(cancelled_events) == 1  # Exactly 1, no duplicate terminal events

        # Now test retrying the cancelled item
        should_fail_first = False
        assert manager.retry_item(job.id, item1.id) is True

        assert wait_for(lambda: manager.get_job(job.id).status == "completed", timeout=10)
        final_summary = manager.get_job(job.id).summary()
        assert final_summary["completed_items"] == 2
        assert final_summary["cancelled_items"] == 0
        assert final_summary["percent"] == 100.0

    finally:
        manager.shutdown()
        store.close()


# ---------------------------------------------------------------------------
# Test 11: Finished stream with unknown size preserves downloaded bytes
# ---------------------------------------------------------------------------
def test_finished_stream_with_unknown_size_preserves_bytes(tmp_path: Path):
    settings = Settings(
        download_dir=tmp_path / "downloads",
        data_dir=tmp_path / "data",
    )
    settings.prepare_dirs()
    store = Store(settings.data_path / "test_preserves.db")
    bus = EventBus()
    bus.attach_loop(DirectLoop())  # type: ignore
    manager = JobManager(settings, store, bus)

    try:
        job = manager.create_job(
            "https://www.youtube.com/watch?v=stream1",
            DownloadOptions(),
            entries=[_entry("stream1", 1)],
        )
        item = job.items[0]

        # 1. Download chunks with unknown total
        manager._on_progress(item, {
            "status": "downloading",
            "downloaded_bytes": 1048576,
            "total_bytes": None,
            "info_dict": {"format_id": "hls_stream"},
        })
        assert item.downloaded == 1048576

        # 2. Status finished arrives without total_bytes (typical in live/chunked streams)
        manager._on_progress(item, {
            "status": "finished",
            "downloaded_bytes": 1048576,
            "total_bytes": None,
            "info_dict": {"format_id": "hls_stream"},
        })
        # Downloaded bytes must NOT be wiped out to 0
        assert item.downloaded == 1048576
        assert item.total == 1048576

    finally:
        manager.shutdown()
        store.close()


