from pathlib import Path

import pytest

from clipyyy import render


def test_campaign_source_audio_builds_crossfaded_track(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(render, "has_audio", lambda _path: False)
    monkeypatch.setattr(render, "run_ffmpeg", lambda args: calls.append(args))

    result = render._render_campaign_source_audio(
        [
            {"source_index": 0, "start_seconds": 1, "end_seconds": 3},
            {"source_index": 1, "start_seconds": 2, "end_seconds": 4},
            {"source_index": 0, "start_seconds": 4, "end_seconds": 6},
        ],
        [
            {"video_path": "/media/first.mp4", "duration_seconds": 10},
            {"video_path": "/media/second.mp4", "duration_seconds": 10},
        ],
        Path("/tmp/campaign-source-audio.m4a"),
        target_duration=5.52,
        volume=1.25,
        transition_seconds=0.24,
    )

    assert result == Path("/tmp/campaign-source-audio.m4a")
    assert len(calls) == 1
    command = calls[0]
    graph = command[command.index("-filter_complex") + 1]
    assert "anullsrc=channel_layout=stereo:sample_rate=48000" in command
    assert graph.count("acrossfade=") == 2
    assert "volume=1.250" in graph
    assert "atrim=duration=5.520" in graph


def test_campaign_source_audio_rejects_unknown_source(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(render, "has_audio", lambda _path: False)
    with pytest.raises(ValueError, match="missing source video"):
        render._render_campaign_source_audio(
            [{"source_index": 2, "start_seconds": 0, "end_seconds": 2}],
            [{"video_path": "/media/first.mp4", "duration_seconds": 10}],
            Path("/tmp/unused.m4a"),
            target_duration=2,
            volume=1,
        )
