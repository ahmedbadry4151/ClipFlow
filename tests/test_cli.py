from __future__ import annotations

import json

from app.cli import _options_from_args, build_parser, main


def test_parser_defaults():
    args = build_parser().parse_args(["download", "https://youtu.be/abc"])
    options = _options_from_args(args)
    assert options.quality == "best"
    assert options.container == "mp4"
    assert options.audio_only is False
    assert options.use_aria2 is True


def test_parser_advanced_flags():
    args = build_parser().parse_args([
        "download",
        "https://youtu.be/abc",
        "--audio", "flac",
        "--items", "1-2,5",
        "--sponsorblock", "remove",
        "--subtitles",
        "--sub-langs", "en,ar",
        "--no-aria2",
        "--fragments", "24",
        "--section", "00:10-00:40",
    ])
    options = _options_from_args(args)
    assert options.audio_only is True
    assert options.audio_format == "flac"
    assert options.playlist_items == "1-2,5"
    assert options.sponsorblock == "remove"
    assert options.subtitles is True
    assert options.subtitle_langs == "en,ar"
    assert options.use_aria2 is False
    assert options.fragments == 24
    assert options.section == "00:10-00:40"


def test_dry_run_json_is_machine_readable(capsys, monkeypatch):
    monkeypatch.setattr(
        "app.cli.expand_playlist",
        lambda *args, **kwargs: [
            {"url": "https://youtu.be/abc", "title": "Example", "index": 1, "duration": 10}
        ],
    )
    assert main(["download", "https://youtu.be/abc", "--dry-run", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["title"] == "Example"


def test_doctor_command(capsys):
    assert main(["doctor"]) == 0
    output = capsys.readouterr().out
    assert "TurboTube doctor" in output


def test_version_flag():
    try:
        build_parser().parse_args(["--version"])
    except SystemExit as exc:
        assert exc.code == 0


def test_serve_parser_open_flag():
    args = build_parser().parse_args(["serve", "--open"])
    assert args.open is True


def test_parser_resume_flags():
    args = build_parser().parse_args(["download", "https://youtu.be/abc"])
    options = _options_from_args(args)
    assert options.resume is True

    args_no_resume = build_parser().parse_args(["download", "https://youtu.be/abc", "--no-resume"])
    options_no_resume = _options_from_args(args_no_resume)
    assert options_no_resume.resume is False


def test_resume_command_help():
    args = build_parser().parse_args(["resume", "job123"])
    assert args.command == "resume"
    assert args.job_id == "job123"


def test_cmd_resume_empty_queue(tmp_path, monkeypatch):
    monkeypatch.setenv("TURBOTUBE_DATA_PATH", str(tmp_path))
    assert main(["resume"]) == 0


def test_cmd_resume_not_found(tmp_path, monkeypatch):
    monkeypatch.setenv("TURBOTUBE_DATA_PATH", str(tmp_path))
    assert main(["resume", "missing_job_id"]) == 1

