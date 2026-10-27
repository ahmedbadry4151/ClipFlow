from __future__ import annotations
import concurrent.futures
import time
from pathlib import Path
import pytest
from app.store import Store


def test_store_pool_basic_crud(tmp_path: Path):
    store = Store(tmp_path / "test.db")
    try:
        job = {
            "id": "j1",
            "url": "https://example.com/1",
            "title": "Job 1",
            "kind": "video",
            "status": "queued",
            "options": "{}",
            "created_at": time.time(),
            "updated_at": time.time(),
            "error": "",
            "total_items": 1,
        }
        item = {
            "id": "i1",
            "job_id": "j1",
            "idx": 1,
            "url": "https://example.com/1",
            "title": "Item 1",
            "duration": 60.0,
            "status": "queued",
            "percent": 0.0,
            "speed": 0.0,
            "eta": None,
            "downloaded": 0,
            "total": 1000,
            "filepath": "",
            "error": "",
            "attempts": 0,
            "created_at": time.time(),
            "updated_at": time.time(),
        }
        store.save_job(job)
        store.save_items([item])

        assert store.count_jobs() == 1
        jobs, items_by_job = store.load(limit=10)
        assert len(jobs) == 1
        assert jobs[0]["id"] == "j1"
        assert len(items_by_job.get("j1", [])) == 1
        assert items_by_job["j1"][0]["id"] == "i1"

        store.delete_job("j1")
        assert store.count_jobs() == 0
    finally:
        store.close()


def test_store_pool_concurrent_access(tmp_path: Path):
    store = Store(tmp_path / "concurrent.db")
    num_threads = 12
    jobs_per_thread = 5

    def worker(worker_id: int):
        for i in range(jobs_per_thread):
            job_id = f"w{worker_id}_j{i}"
            item_id = f"w{worker_id}_i{i}"
            now = time.time()
            store.save_job({
                "id": job_id,
                "url": f"https://example.com/{job_id}",
                "title": f"Title {job_id}",
                "kind": "video",
                "status": "queued",
                "options": "{}",
                "created_at": now,
                "updated_at": now,
                "error": "",
                "total_items": 1,
            })
            store.save_items([{
                "id": item_id,
                "job_id": job_id,
                "idx": 1,
                "url": f"https://example.com/{job_id}",
                "title": f"Title {item_id}",
                "duration": 10.0,
                "status": "queued",
                "percent": 0.0,
                "speed": 0.0,
                "eta": None,
                "downloaded": 0,
                "total": 100,
                "filepath": "",
                "error": "",
                "attempts": 0,
                "created_at": now,
                "updated_at": now,
            }])
            # Concurrent read
            c = store.count_jobs()
            assert c > 0
            _jobs, _items = store.load(limit=20)

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as pool:
            futures = [pool.submit(worker, w) for w in range(num_threads)]
            for f in concurrent.futures.as_completed(futures):
                f.result()

        assert store.count_jobs() == num_threads * jobs_per_thread
    finally:
        store.close()
