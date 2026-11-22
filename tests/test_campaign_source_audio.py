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


def test_campaign_source_audio_uses_beat_aligned_shot_durations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(render, "has_audio", lambda _path: False)
    monkeypatch.setattr(render, "select_music_cut_duration", lambda *_args: 1.5)
    monkeypatch.setattr(render, "run_ffmpeg", lambda args: calls.append(args))

    render._render_campaign_source_audio(
        [
            {"source_index": 0, "start_seconds": 0, "end_seconds": 2},
            {"source_index": 0, "start_seconds": 2, "end_seconds": 4},
            {"source_index": 0, "start_seconds": 4, "end_seconds": 6},
        ],
        [{"video_path": "/media/source.mp4", "duration_seconds": 10}],
        Path("/tmp/beat-aligned-source-audio.m4a"),
        target_duration=4.5,
        volume=1,
        transition_seconds=0.0,
        music_analysis={"beat_times": [1.5], "best_start_seconds": 0},
    )

    assert len(calls) == 1
    assert calls[0].count("1.500") == 3
    graph = calls[0][calls[0].index("-filter_complex") + 1]
    assert "atempo=1.00000" not in graph


def test_campaign_music_mix_filter_ducks_music_under_source_audio() -> None:
    graph = render._campaign_music_mix_filter("volume=0.9", source_audio=True, duck_music=True)

    assert "sidechaincompress=threshold=0.03:ratio=6:attack=20:release=350" in graph
    assert "[ducked][src]amix=inputs=2" in graph


def test_campaign_music_mix_filter_keeps_default_mix_unchanged() -> None:
    graph = render._campaign_music_mix_filter("volume=0.9", source_audio=True, duck_music=False)

    assert "sidechaincompress" not in graph
    assert "[music][src]amix=inputs=2" in graph


def test_campaign_music_mix_filter_ignores_ducking_without_source_audio() -> None:
    graph = render._campaign_music_mix_filter("volume=0.9", source_audio=False, duck_music=True)

    assert "sidechaincompress" not in graph
    assert graph.endswith("[music]anull[aout]")
