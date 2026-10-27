from __future__ import annotations

import json
import queue
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Iterable

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'video',
    status TEXT NOT NULL DEFAULT 'queued',
    options TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    error TEXT NOT NULL DEFAULT '',
    total_items INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    idx INTEGER NOT NULL DEFAULT 0,
    url TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    duration REAL,
    status TEXT NOT NULL DEFAULT 'queued',
    percent REAL NOT NULL DEFAULT 0,
    speed REAL NOT NULL DEFAULT 0,
    eta REAL,
    downloaded INTEGER NOT NULL DEFAULT 0,
    total INTEGER NOT NULL DEFAULT 0,
    filepath TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_items_job ON items(job_id, idx);
CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at DESC);
"""

_ITEM_FIELDS = (
    "id",
    "job_id",
    "idx",
    "url",
    "title",
    "duration",
    "status",
    "percent",
    "speed",
    "eta",
    "downloaded",
    "total",
    "filepath",
    "error",
    "attempts",
    "created_at",
    "updated_at",
)

_JOB_FIELDS = (
    "id",
    "url",
    "title",
    "kind",
    "status",
    "options",
    "created_at",
    "updated_at",
    "error",
    "total_items",
)

_POOL_SIZE = 4


class Store:
    """SQLite persistence layer with thread-safe pooled connections and WAL mode."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = str(path)
        self._write_lock = threading.Lock()
        self._pool: queue.SimpleQueue[sqlite3.Connection] = queue.SimpleQueue()
        
        # Initialize schema with bootstrap connection
        bootstrap = self._create_connection()
        bootstrap.executescript(_SCHEMA)
        bootstrap.commit()
        bootstrap.close()

        for _ in range(_POOL_SIZE):
            self._pool.put(self._create_connection())

    def _create_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, check_same_thread=False, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _acquire(self) -> sqlite3.Connection:
        try:
            return self._pool.get_nowait()
        except queue.Empty:
            return self._create_connection()

    def _release(self, conn: sqlite3.Connection) -> None:
        if self._pool.qsize() >= _POOL_SIZE:
            try:
                conn.close()
            except Exception:
                pass
        else:
            self._pool.put(conn)

    # -- writes ---------------------------------------------------------
    def save_job(self, job: dict[str, Any]) -> None:
        values = [job.get(field) for field in _JOB_FIELDS]
        placeholders = ", ".join("?" for _ in _JOB_FIELDS)
        columns = ", ".join(_JOB_FIELDS)
        updates = ", ".join(f"{field}=excluded.{field}" for field in _JOB_FIELDS if field != "id")
        conn = self._acquire()
        try:
            with self._write_lock:
                conn.execute(
                    f"INSERT INTO jobs ({columns}) VALUES ({placeholders}) "
                    f"ON CONFLICT(id) DO UPDATE SET {updates}",
                    values,
                )
                conn.commit()
        finally:
            self._release(conn)

    def save_items(self, items: Iterable[dict[str, Any]]) -> None:
        rows = [[item.get(field) for field in _ITEM_FIELDS] for item in items]
        if not rows:
            return
        placeholders = ", ".join("?" for _ in _ITEM_FIELDS)
        columns = ", ".join(_ITEM_FIELDS)
        updates = ", ".join(f"{field}=excluded.{field}" for field in _ITEM_FIELDS if field != "id")
        conn = self._acquire()
        try:
            with self._write_lock:
                conn.executemany(
                    f"INSERT INTO items ({columns}) VALUES ({placeholders}) "
                    f"ON CONFLICT(id) DO UPDATE SET {updates}",
                    rows,
                )
                conn.commit()
        finally:
            self._release(conn)

    def delete_job(self, job_id: str) -> None:
        conn = self._acquire()
        try:
            with self._write_lock:
                conn.execute("DELETE FROM items WHERE job_id = ?", (job_id,))
                conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
                conn.commit()
        finally:
            self._release(conn)

    def prune(self, keep: int) -> None:
        conn = self._acquire()
        try:
            with self._write_lock:
                rows = conn.execute(
                    "SELECT id FROM jobs ORDER BY created_at DESC LIMIT -1 OFFSET ?", (keep,)
                ).fetchall()
                for row in rows:
                    conn.execute("DELETE FROM items WHERE job_id = ?", (row["id"],))
                    conn.execute("DELETE FROM jobs WHERE id = ?", (row["id"],))
                conn.commit()
        finally:
            self._release(conn)

    # -- reads ----------------------------------------------------------
    def load(self, limit: int = 500) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
        conn = self._acquire()
        try:
            job_rows = conn.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
            jobs = [self._row_to_job(row) for row in job_rows]
            by_id: dict[str, list[dict[str, Any]]] = {job["id"]: [] for job in jobs}
            if by_id:
                placeholders = ", ".join("?" for _ in by_id)
                item_rows = conn.execute(
                    f"SELECT * FROM items WHERE job_id IN ({placeholders}) ORDER BY idx ASC",
                    tuple(by_id),
                ).fetchall()
                for row in item_rows:
                    by_id[row["job_id"]].append(dict(row))
            return jobs, by_id
        finally:
            self._release(conn)

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> dict[str, Any]:
        job = dict(row)
        try:
            job["options"] = json.loads(job.get("options") or "{}")
        except (TypeError, json.JSONDecodeError):
            job["options"] = {}
        return job

    def count_jobs(self) -> int:
        conn = self._acquire()
        try:
            row = conn.execute("SELECT COUNT(*) AS n FROM jobs").fetchone()
            return int(row["n"]) if row else 0
        finally:
            self._release(conn)

    def close(self) -> None:
        while True:
            try:
                conn = self._pool.get_nowait()
                try:
                    conn.commit()
                    conn.close()
                except sqlite3.Error:
                    pass
            except queue.Empty:
                break
