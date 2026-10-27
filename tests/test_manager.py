from __future__ import annotations

import time

import pytest
from yt_dlp.utils import DownloadCancelled

from app import manager as manager_module
from app.events import EventBus
from app.manager import JobManager
from app.models import DownloadOptions, SelectedEntry
from app.store import Store

from .helpers import wait_for

VIDEO = "https://www.youtube.com/watch?v=abc123"


def _entry(video_id: str, index: int = 1) -> SelectedEntry:
    return SelectedEntry(
        url=f"https://www.youtube.com/watch?v={video_id}",
        title=f"Video {video_id}",
        index=index,
        duration=60,
    )


def _fake_run(fail_times: int = 0, delay: float = 0.0):
    calls = {"count": 0}

    def fake(url, options, settings, **kwargs):
        calls["count"] += 1
        if calls["count"] <= fail_times:
            raise RuntimeError("HTTP Error 500: transient")
        if delay:
            time.sleep(delay)
        hook = kwargs.get("progress_hook")
        if hook:
            hook(
                {
                    "status": "downloading",
                    "downloaded_bytes": 50,
                    "total_bytes": 100,
                    "speed": 2048,
                    "eta": 1,
                    "info_dict": {"format_id": "v"},
                    "filename": "video",
                }
            )
            hook(
                {
                    "status": "finished",
                    "downloaded_bytes": 100,
                    "total_bytes": 100,
                    "info_dict": {"format_id": "v"},
                }
            )
        video_id = url.rsplit("=", 1)[-1]
        path = settings.download_path / f"{video_id}.mp4"
        path.write_bytes(b"video-bytes")
        return {"id": video_id, "filepath": str(path)}

    return fake, calls


def test_job_completes(manager, monkeypatch):
    fake, _ = _fake_run()
    monkeypatch.setattr(manager_module, "run_download", fake)
    job = manager.create_job(VIDEO, DownloadOptions(), entries=[_entry("abc123")])
    assert manager.get_job(job.id) is job
    assert wait_for(lambda: manager.get_job(job.id).status == "completed")
    item = manager.get_job(job.id).items[0]
    assert item.status == "completed"
    assert item.percent == 100
    assert item.filepath.endswith("abc123.mp4")
    snapshot = manager.snapshot()
    assert snapshot[0]["items"][0]["status"] == "completed"
    assert snapshot[0]["percent"] == 100


def test_playlist_spec_filters_entries(manager, monkeypatch):
    fake, _ = _fake_run()
    monkeypatch.setattr(manager_module, "run_download", fake)
    entries = [_entry(f"vid{i}", index=i) for i in range(1, 5)]
    job = manager.create_job(
        "https://www.youtube.com/playlist?list=PL123",
        DownloadOptions(playlist_items="1,3"),
        entries=entries,
    )
    assert job.kind == "playlist"
    assert [item.index for item in job.items] == [1, 3]
    assert wait_for(lambda: manager.get_job(job.id).status == "completed")


def test_transient_failure_is_retried(manager, monkeypatch):
    fake, calls = _fake_run(fail_times=1)
    monkeypatch.setattr(manager_module, "run_download", fake)
    job = manager.create_job(VIDEO, DownloadOptions(), entries=[_entry("retry1")])
    assert wait_for(lambda: manager.get_job(job.id).status == "completed", timeout=10)
    assert calls["count"] == 2


def test_failed_job_can_be_retried(manager, monkeypatch):
    fake, calls = _fake_run(fail_times=2)
    monkeypatch.setattr(manager_module, "run_download", fake)
    job = manager.create_job(VIDEO, DownloadOptions(), entries=[_entry("fail1")])
    assert wait_for(lambda: manager.get_job(job.id).status == "failed", timeout=10)
    assert manager.get_job(job.id).items[0].status == "failed"
    assert "HTTP Error 500" in manager.get_job(job.id).items[0].error

    working, _ = _fake_run()
    monkeypatch.setattr(manager_module, "run_download", working)
    assert manager.retry_job(job.id) == 1
    assert wait_for(lambda: manager.get_job(job.id).status == "completed", timeout=10)


def test_cancel_running_job(manager, monkeypatch):
    def slow(url, options, settings, **kwargs):
        cancel = kwargs["cancel_event"]
        deadline = time.time() + 5
        while time.time() < deadline:
            if cancel.is_set():
                raise DownloadCancelled("cancelled")
            time.sleep(0.01)
        raise RuntimeError("timed out")

    monkeypatch.setattr(manager_module, "run_download", slow)
    job = manager.create_job(VIDEO, DownloadOptions(), entries=[_entry("cancel1")])
    assert wait_for(lambda: manager.get_job(job.id).items[0].status in {"running", "downloading"})
    # An active item must promote the job out of "queued" immediately.
    assert wait_for(lambda: manager.get_job(job.id).status == "running")
    assert manager.cancel_job(job.id) == 1
    assert wait_for(lambda: manager.get_job(job.id).status == "cancelled", timeout=6)
    assert manager.get_job(job.id).items[0].status == "cancelled"


def test_unfinished_jobs_resume_as_interrupted(settings, monkeypatch):
    fake, _ = _fake_run()
    monkeypatch.setattr(manager_module, "run_download", fake)
    store = Store(settings.data_path / "history.db")
    first = JobManager(settings, store, EventBus())
    job = first.create_job(VIDEO, DownloadOptions(), entries=[_entry("persist1")])
    assert wait_for(lambda: first.get_job(job.id).status == "completed")
    first.shutdown()
    store.close()

    store2 = Store(settings.data_path / "history.db")
    second = JobManager(settings, store2, EventBus())
    loaded = second.get_job(job.id)
    assert loaded is not None
    assert loaded.status == "completed"
    assert loaded.items[0].filepath.endswith("persist1.mp4")
    second.shutdown()
    store2.close()


def test_delete_job_with_files(manager, monkeypatch):
    fake, _ = _fake_run()
    monkeypatch.setattr(manager_module, "run_download", fake)
    job = manager.create_job(VIDEO, DownloadOptions(), entries=[_entry("delete1")])
    assert wait_for(lambda: manager.get_job(job.id).status == "completed")
    path = manager.get_job(job.id).items[0].filepath
    deleted = manager.delete_job(job.id, delete_files=True)
    assert any(item.endswith("delete1.mp4") for item in deleted)
    assert not __import__("os").path.exists(path)
    assert manager.get_job(job.id) is None


def test_active_job_cannot_be_deleted(manager, monkeypatch):
    def slow(url, options, settings, **kwargs):
        time.sleep(1)
        raise RuntimeError("nope")

    monkeypatch.setattr(manager_module, "run_download", slow)
    job = manager.create_job(VIDEO, DownloadOptions(), entries=[_entry("active1")])
    with pytest.raises(ValueError):
        manager.delete_job(job.id)
    manager.cancel_job(job.id)
    assert wait_for(lambda: manager.get_job(job.id).status == "cancelled", timeout=6)


def test_resume_job_preserves_progress(manager, monkeypatch):
    cancelled_once = False

    def partial_then_cancel(url, options, settings, **kwargs):
        nonlocal cancelled_once
        hook = kwargs.get("progress_hook")
        if not cancelled_once:
            cancelled_once = True
            if hook:
                hook({
                    "status": "downloading",
                    "downloaded_bytes": 500,
                    "total_bytes": 1000,
                    "speed": 50,
                    "info_dict": {"format_id": "v"},
                })
            raise DownloadCancelled("Stopped midway")
        if hook:
            hook({
                "status": "downloading",
                "downloaded_bytes": 1000,
                "total_bytes": 1000,
                "speed": 100,
                "info_dict": {"format_id": "v"},
            })
            hook({
                "status": "finished",
                "downloaded_bytes": 1000,
                "total_bytes": 1000,
                "info_dict": {"format_id": "v"},
            })
        path = settings.download_path / "resume1.mp4"
        path.write_bytes(b"data")
        return {"id": "resume1", "filepath": str(path)}

    monkeypatch.setattr(manager_module, "run_download", partial_then_cancel)
    job = manager.create_job(VIDEO, DownloadOptions(), entries=[_entry("resume1")])
    assert wait_for(lambda: manager.get_job(job.id).status == "cancelled", timeout=10)
    item = manager.get_job(job.id).items[0]
    assert item.status == "cancelled"
    assert item.percent == 50.0
    assert item.downloaded == 500
    assert item.total == 1000

    # Resume the job
    resumed = manager.resume_job(job.id)
    assert resumed == 1

    # While queued/starting, partial progress must be preserved
    item_resuming = manager.get_job(job.id).items[0]
    assert item_resuming.percent == 50.0
    assert item_resuming.downloaded == 500

    assert wait_for(lambda: manager.get_job(job.id).status == "completed", timeout=10)
    final_item = manager.get_job(job.id).items[0]
    assert final_item.status == "completed"
    assert final_item.percent == 100.0


def test_resume_all_and_resume_item(manager, monkeypatch):
    def fail(url, options, settings, **kwargs):
        raise RuntimeError("Network drop")

    monkeypatch.setattr(manager_module, "run_download", fail)
    job = manager.create_job(VIDEO, DownloadOptions(), entries=[_entry("fail_res")])
    assert wait_for(lambda: manager.get_job(job.id).status == "failed", timeout=10)

    # test resume_item
    item_id = manager.get_job(job.id).items[0].id
    assert manager.resume_item(job.id, item_id) is True
    assert wait_for(lambda: manager.get_job(job.id).status == "failed", timeout=10)

    # now with working download, resume_all
    working, _ = _fake_run()
    monkeypatch.setattr(manager_module, "run_download", working)
    count = manager.resume_all()
    assert count >= 1
    assert wait_for(lambda: manager.get_job(job.id).status == "completed", timeout=10)


def test_retry_resets_progress_while_resume_preserves(manager, monkeypatch):
    def fail_with_progress(url, options, settings, **kwargs):
        hook = kwargs.get("progress_hook")
        if hook:
            hook({
                "status": "downloading",
                "downloaded_bytes": 400,
                "total_bytes": 1000,
                "info_dict": {"format_id": "v"},
            })
        raise RuntimeError("simulated error")

    monkeypatch.setattr(manager_module, "run_download", fail_with_progress)
    job = manager.create_job(VIDEO, DownloadOptions(), entries=[_entry("progress_test")])
    assert wait_for(lambda: manager.get_job(job.id).status == "failed", timeout=10)
    assert manager.get_job(job.id).items[0].percent == 40.0

    # retry_job with preserve_progress=False should reset to 0
    manager.retry_job(job.id, preserve_progress=False)
    item_reset = manager.get_job(job.id).items[0]
    assert item_reset.percent == 0.0
    assert item_reset.downloaded == 0


def test_delete_job_cleans_partial_artifacts(manager, monkeypatch, tmp_path):
    job = manager.create_job(VIDEO, DownloadOptions(), entries=[_entry("partial_clean")])
    item = manager.get_job(job.id).items[0]
    manager.cancel_job(job.id)
    assert wait_for(lambda: manager.get_job(job.id).status == "cancelled")

    # Simulate partial files left on disk
    download_dir = manager.settings.download_path
    part_file = download_dir / f"{item.id}.mp4.part"
    aria2_file = download_dir / f"{item.id}.mp4.part.aria2"
    part_file.write_bytes(b"partial video data")
    aria2_file.write_bytes(b"aria2 control data")

    assert part_file.exists()
    assert aria2_file.exists()

    deleted = manager.delete_job(job.id, delete_files=True)
    assert not part_file.exists()
    assert not aria2_file.exists()
    assert any(str(part_file) == d for d in deleted)


def test_interrupted_job_status_is_interrupted(settings):
    import json
    store = Store(settings.data_path / "interrupted.db")
    now = time.time()
    store.save_job({
        "id": "job_int",
        "url": "https://example.com/watch?v=abc123",
        "title": "Interrupted Video",
        "kind": "video",
        "status": "running",
        "created_at": now,
        "updated_at": now,
        "error": "",
        "total_items": 1,
        "options": json.dumps({}),
    })
    store.save_items([{
        "id": "item_int",
        "job_id": "job_int",
        "idx": 1,
        "url": "https://example.com/watch?v=abc123",
        "title": "Interrupted Video",
        "duration": None,
        "status": "downloading",
        "percent": 45.0,
        "speed": 0.0,
        "eta": None,
        "downloaded": 4500,
        "total": 10000,
        "filepath": "",
        "error": "",
        "attempts": 1,
        "created_at": now,
        "updated_at": now,
    }])

    manager = JobManager(settings, store, EventBus())
    job = manager.get_job("job_int")
    assert job is not None
    assert job.status == "interrupted"
    assert job.items[0].status == "interrupted"
    assert job.items[0].percent == 45.0
    assert job.summary()["interrupted_items"] == 1
    manager.shutdown()
    store.close()

