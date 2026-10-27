from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.api import delete_file, list_files


def run_coro(coro):
    """Run an async coroutine that has no IO waits without needing an event loop socketpair."""
    try:
        coro.send(None)
    except StopIteration as e:
        return e.value
    raise RuntimeError("Coroutine did not complete synchronously")


def _mock_request(settings):
    req = MagicMock()
    req.app.state.settings = settings
    return req


def test_list_files_empty(settings):
    req = _mock_request(settings)
    result = run_coro(list_files(req))
    assert result == []


def test_list_files_with_items_and_search(settings):
    req = _mock_request(settings)
    file1 = settings.download_path / "song1.mp3"
    file1.write_bytes(b"12345")
    file2 = settings.download_path / "video1.mp4"
    file2.write_bytes(b"1234567890")

    result = run_coro(list_files(req))
    assert len(result) == 2
    names = [f["name"] for f in result]
    assert "song1.mp3" in names
    assert "video1.mp4" in names

    # Test search filter
    filtered = run_coro(list_files(req, search="song"))
    assert len(filtered) == 1
    assert filtered[0]["name"] == "song1.mp3"
    assert filtered[0]["extension"] == "mp3"
    assert filtered[0]["size"] == 5


def test_delete_file_success(settings):
    req = _mock_request(settings)
    test_file = settings.download_path / "clip.mp4"
    test_file.write_bytes(b"content")
    assert test_file.exists()

    result = run_coro(delete_file("clip.mp4", req))
    assert result["deleted"] is True
    assert not test_file.exists()


def test_delete_file_not_found(settings):
    req = _mock_request(settings)
    with pytest.raises(HTTPException) as exc:
        run_coro(delete_file("missing.mp4", req))
    assert exc.value.status_code == 404


def test_delete_file_traversal_blocked(settings):
    req = _mock_request(settings)
    with pytest.raises(HTTPException) as exc:
        run_coro(delete_file("../secret.txt", req))
    assert exc.value.status_code == 400


def test_open_file_success(settings, monkeypatch):
    from app.api import open_file

    req = _mock_request(settings)
    test_file = settings.download_path / "track.mp3"
    test_file.write_bytes(b"music")

    opened = []
    if hasattr(pytest, "MonkeyPatch"):
        import os
        monkeypatch.setattr(os, "startfile", lambda p: opened.append(p), raising=False)
    
    result = run_coro(open_file("track.mp3", req))
    assert result["opened"] == "track.mp3"


def test_open_file_not_found(settings):
    from app.api import open_file

    req = _mock_request(settings)
    with pytest.raises(HTTPException) as exc:
        run_coro(open_file("nonexistent.mp4", req))
    assert exc.value.status_code == 404


def test_open_file_traversal_blocked(settings):
    from app.api import open_file

    req = _mock_request(settings)
    with pytest.raises(HTTPException) as exc:
        run_coro(open_file("../outside.txt", req))
    assert exc.value.status_code == 400


def test_clean_temp_files(settings):
    from app.api import clean_temp_files

    req = _mock_request(settings)
    part_file = settings.download_path / "video.mp4.part"
    part_file.write_bytes(b"temp123")
    ytdl_file = settings.download_path / "audio.m4a.ytdl"
    ytdl_file.write_bytes(b"temp4567")
    aria2_file = settings.download_path / "video.mp4.part.aria2"
    aria2_file.write_bytes(b"ctrl89")
    normal_file = settings.download_path / "completed.mp4"
    normal_file.write_bytes(b"final")

    result = run_coro(clean_temp_files(req))
    assert result["cleaned"] == 3
    assert result["bytes_freed"] == len(b"temp123") + len(b"temp4567") + len(b"ctrl89")
    assert not part_file.exists()
    assert not ytdl_file.exists()
    assert not aria2_file.exists()
    assert normal_file.exists()


def test_static_index_content():
    index_file = Path("app/static/index.html")
    assert index_file.is_file()
    content = index_file.read_text(encoding="utf-8")
    assert "TurboTube" in content
    assert "ClipFlow" in content
    assert 'data-theme="light"' in content
    assert "Download Studio" in content
    assert 'id="form"' in content
    assert 'id="url"' in content
    assert 'id="jobs"' in content

