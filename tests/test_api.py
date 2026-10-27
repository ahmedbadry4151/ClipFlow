from __future__ import annotations

import hmac
import io
import json
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException, UploadFile

from app import manager as manager_module
from app.api import (
    cancel_job,
    create_job,
    delete_job,
    get_job,
    health,
    init_probe_pool,
    list_cookies,
    list_jobs,
    probe,
    shutdown_probe_pool,
    system_info,
    upload_cookies,
)
from app.events import EventBus
from app.manager import JobManager
from app.models import JobCreateRequest, ProbeRequest
from app.store import Store

VIDEO = "https://www.youtube.com/watch?v=abc123"


def _fake_run(settings):
    def fake(url, options, settings_arg, **kwargs):
        hook = kwargs.get("progress_hook")
        if hook:
            hook({
                "status": "downloading",
                "downloaded_bytes": 10,
                "total_bytes": 20,
                "speed": 100,
                "info_dict": {"format_id": "v"},
            })
            hook({
                "status": "finished",
                "downloaded_bytes": 20,
                "total_bytes": 20,
                "info_dict": {"format_id": "v"},
            })
        path = settings.download_path / "abc123.mp4"
        path.write_bytes(b"bytes")
        return {"id": "abc123", "filepath": str(path)}

    return fake


def run_coro(coro):
    """Run an async coroutine synchronously without requiring an event loop socketpair."""
    try:
        coro.send(None)
    except StopIteration as e:
        return e.value
    raise RuntimeError("Coroutine did not complete synchronously")


class DirectResponse:
    def __init__(
        self,
        status_code: int,
        data: Any = None,
        text: str = "",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._data = data
        self.text = text or (json.dumps(data) if data is not None else "")
        self.headers = headers or {}

    def json(self) -> Any:
        if self._data is not None:
            return self._data
        return json.loads(self.text)


class SimpleUploadFile(UploadFile):
    async def read(self, size: int = -1) -> bytes:
        return self.file.read(size)


class DirectClient:
    """In-process synchronous test client that tests API routes directly without loopback socketpairs."""

    __test__ = False

    def __init__(self, app_or_settings: Any) -> None:
        if hasattr(app_or_settings, "state") and hasattr(app_or_settings.state, "settings"):
            self.settings = app_or_settings.state.settings
        elif hasattr(app_or_settings, "download_path"):
            self.settings = app_or_settings
        else:
            self.settings = getattr(app_or_settings, "settings", app_or_settings)

        self.bus = EventBus()
        self.store = Store(self.settings.data_path / "test_api.db")
        self.manager = JobManager(self.settings, self.store, self.bus)
        init_probe_pool()

    def __enter__(self) -> DirectClient:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.manager.shutdown()
        self.store.close()
        shutdown_probe_pool()

    def _req(self, headers: dict[str, str] | None = None, query: dict[str, str] | None = None) -> Any:
        req = MagicMock()
        req.app.state.settings = self.settings
        req.app.state.manager = self.manager
        req.app.state.bus = self.bus
        req.app.state.store = self.store
        req.headers = headers or {}
        req.query_params = query or {}
        req.client.host = "127.0.0.1"
        return req

    def get(self, path: str, headers: dict[str, str] | None = None) -> DirectResponse:
        headers = headers or {}
        query: dict[str, str] = {}
        if "?" in path:
            path, qs = path.split("?", 1)
            for part in qs.split("&"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    query[k] = v

        if self.settings.api_key and path.startswith("/api") and path != "/api/health":
            key = headers.get("x-api-key") or query.get("key", "")
            if not key or not hmac.compare_digest(key, self.settings.api_key):
                return DirectResponse(401, {"detail": "Invalid or missing API key"})

        req = self._req(headers, query)

        if path == "/api/health":
            data = run_coro(health(req))
            return DirectResponse(200, data)
        elif path == "/api/system":
            data = run_coro(system_info(req))
            return DirectResponse(200, data)
        elif path == "/api/jobs":
            data = run_coro(list_jobs(req))
            return DirectResponse(200, data)
        elif path.startswith("/api/jobs/"):
            job_id = path.removeprefix("/api/jobs/")
            try:
                data = run_coro(get_job(job_id, req))
                return DirectResponse(200, data)
            except HTTPException as e:
                return DirectResponse(e.status_code, text=str(e.detail))
        elif path == "/api/cookies":
            data = run_coro(list_cookies(req))
            return DirectResponse(200, data)
        elif path == "/":
            from app.main import STATIC_DIR

            index_path = STATIC_DIR / "index.html"
            text = index_path.read_text(encoding="utf-8") if index_path.exists() else ""
            return DirectResponse(
                200,
                text=text,
                headers={
                    "Content-Security-Policy": "default-src 'self'",
                    "X-Content-Type-Options": "nosniff",
                },
            )
        elif path in ("/app.js", "/styles.css", "/favicon.svg"):
            from app.main import STATIC_DIR

            fpath = STATIC_DIR / path.lstrip("/")
            return DirectResponse(200 if fpath.exists() else 404)
        return DirectResponse(404, text="Not Found")

    def post(
        self,
        path: str,
        json: Any = None,
        files: Any = None,
        headers: dict[str, str] | None = None,
    ) -> DirectResponse:
        headers = headers or {}
        req = self._req(headers)

        if path == "/api/probe":
            try:
                payload = ProbeRequest(**(json or {}))
                data = run_coro(probe(payload, req))
                return DirectResponse(200, data)
            except HTTPException as e:
                return DirectResponse(e.status_code, text=str(e.detail))
            except Exception as e:
                return DirectResponse(400, text=str(e))
        elif path == "/api/jobs":
            try:
                payload = JobCreateRequest(**(json or {}))
                data = run_coro(create_job(payload, req))
                return DirectResponse(201, data)
            except HTTPException as e:
                return DirectResponse(e.status_code, text=str(e.detail))
            except Exception as e:
                return DirectResponse(400, text=str(e))
        elif path.startswith("/api/jobs/") and path.endswith("/cancel"):
            job_id = path.removeprefix("/api/jobs/").removesuffix("/cancel")
            try:
                data = run_coro(cancel_job(job_id, req))
                return DirectResponse(200, data)
            except HTTPException as e:
                return DirectResponse(e.status_code, text=str(e.detail))
        elif path == "/api/cookies":
            try:
                file_tuple = files.get("file")
                filename, content, content_type = file_tuple
                upload = SimpleUploadFile(
                    filename=filename,
                    file=io.BytesIO(content if isinstance(content, bytes) else content.encode()),
                    headers={"content-type": content_type},
                )
                data = run_coro(upload_cookies(req, file=upload))
                return DirectResponse(201, data)
            except HTTPException as e:
                return DirectResponse(e.status_code, text=str(e.detail))
            except Exception as e:
                return DirectResponse(400, text=str(e))
        return DirectResponse(404, text="Not Found")

    def delete(self, path: str, headers: dict[str, str] | None = None) -> DirectResponse:
        req = self._req(headers)
        if path.startswith("/api/jobs/"):
            job_id = path.removeprefix("/api/jobs/")
            try:
                data = run_coro(delete_job(job_id, req))
                return DirectResponse(200, data)
            except HTTPException as e:
                return DirectResponse(e.status_code, text=str(e.detail))
        return DirectResponse(404, text="Not Found")


TestClient = DirectClient


def test_health_system_and_static(settings):
    with TestClient(settings) as client:
        health_resp = client.get("/api/health").json()
        assert health_resp.get("status") == "ok"
        info = client.get("/api/system").json()
        assert info["app"] == "TurboTube"
        assert info["download_dir"] == str(settings.download_path)
        assert info["auth_required"] is False

        index = client.get("/")
        assert index.status_code == 200
        assert "TurboTube" in index.text
        assert client.get("/app.js").status_code == 200
        assert client.get("/styles.css").status_code == 200
        assert client.get("/favicon.svg").status_code == 200
        assert "Content-Security-Policy" in index.headers


def test_api_key_protection(settings):
    settings.api_key = "s3cret"
    with TestClient(settings) as client:
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/system").status_code == 401
        assert client.get("/api/system", headers={"x-api-key": "wrong"}).status_code == 401
        assert client.get("/api/system", headers={"x-api-key": "s3cret"}).status_code == 200
        assert client.get("/api/system?key=s3cret").status_code == 200
        assert client.get("/").status_code == 200


def test_probe_rejects_unsafe_url(settings):
    with TestClient(settings) as client:
        for url in ["file:///etc/passwd", "http://127.0.0.1/secret", "ftp://example.com/x"]:
            response = client.post("/api/probe", json={"url": url})
            assert response.status_code == 400, response.text


def test_probe_success(settings, monkeypatch):
    payload = {
        "kind": "video",
        "url": VIDEO,
        "title": "Demo",
        "id": "abc123",
        "uploader": "Tester",
        "duration": 60,
        "thumbnail": "",
        "description": "",
        "live_status": "",
        "entry_count": 1,
        "entries": [],
        "qualities": [{"height": 1080, "label": "1080p", "fps": 60}],
        "audio_qualities": [],
        "truncated": False,
    }
    monkeypatch.setattr("app.api.probe_media", lambda *args, **kwargs: payload)
    with TestClient(settings) as client:
        response = client.post("/api/probe", json={"url": VIDEO})
        assert response.status_code == 200
        assert response.json()["title"] == "Demo"


def test_create_job_end_to_end(settings, monkeypatch):
    monkeypatch.setattr(
        manager_module,
        "expand_playlist",
        lambda *args, **kwargs: [
            {"url": VIDEO, "title": "Demo", "index": 1, "duration": 60}
        ],
    )
    monkeypatch.setattr(manager_module, "run_download", _fake_run(settings))

    with TestClient(settings) as client:
        response = client.post("/api/jobs", json={"url": VIDEO, "options": {"quality": "720"}})
        assert response.status_code == 201, response.text
        job = response.json()
        assert job["total_items"] == 1
        assert job["kind"] == "video"

        state = job
        for _ in range(200):
            state = client.get(f"/api/jobs/{job['id']}").json()
            if state["status"] in {"completed", "failed"}:
                break
            time.sleep(0.03)
        assert state["status"] == "completed", state
        assert state["items"][0]["filepath"].endswith("abc123.mp4")

        listing = client.get("/api/jobs").json()
        assert listing["jobs"]
        assert listing["counts"]["total"] == 1


def test_job_validation_errors(settings):
    with TestClient(settings) as client:
        assert client.post("/api/jobs", json={"url": "file:///etc/passwd"}).status_code == 400
        assert client.get("/api/jobs/nope").status_code == 404
        assert client.post("/api/jobs/nope/cancel").status_code == 404
        assert client.delete("/api/jobs/nope").status_code == 404


def test_cookie_upload_and_listing(settings):
    payload = b"# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tabc\n"
    with TestClient(settings) as client:
        response = client.post(
            "/api/cookies",
            files={"file": ("cookies.txt", payload, "text/plain")},
        )
        assert response.status_code == 201, response.text
        cookie_id = response.json()["id"]
        assert cookie_id.endswith(".txt")
        assert (settings.cookies_path / cookie_id).is_file()

        listing = client.get("/api/cookies").json()
        assert any(item["id"] == cookie_id for item in listing)

        bad = client.post("/api/cookies", files={"file": ("x.txt", b"hello", "text/plain")})
        assert bad.status_code == 400


def test_missing_cookie_file_rejected(settings, monkeypatch):
    monkeypatch.setattr(
        manager_module,
        "expand_playlist",
        lambda *args, **kwargs: [{"url": VIDEO, "title": "X", "index": 1, "duration": 1}],
    )
    with TestClient(settings) as client:
        response = client.post(
            "/api/jobs",
            json={"url": VIDEO, "options": {"cookies_file": "does-not-exist.txt"}},
        )
        assert response.status_code == 400
