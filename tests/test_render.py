"""Render a synthetic video end to end with ffmpeg (no network, no models)."""

import pytest

from clipyyy.media import find_ffmpeg, has_audio, probe, run_ffmpeg
from clipyyy.reframe import center_plan
from clipyyy.render import crop_filter, render_clips
from clipyyy.timeline import plan_timeline

pytestmark = pytest.mark.skipif(not find_ffmpeg().ffmpeg, reason="needs ffmpeg")


@pytest.mark.parametrize("aspect,size", [("9:16", (1080, 1920)), ("1:1", (1080, 1080))])
def test_render_synthetic_clip(tmp_path, transcript, aspect, size):
    source = tmp_path / "source.mp4"
    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=1280x720:rate=30:duration=40",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=40",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-c:a",
            "aac",
            "-shortest",
            str(source),
        ]
    )
    selection = {"clips": [{"rank": 1, "start_seconds": 6.0, "end_seconds": 23.4, "title": "Test clip"}]}
    timeline = plan_timeline(selection, transcript, broll=False)
    speaker = tmp_path / "work" / "clip-01" / "speaker.mp4"
    speaker.parent.mkdir(parents=True)
    run_ffmpeg(
        [
            "-ss",
            "6",
            "-to",
            "23.4",
            "-i",
            str(source),
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            str(speaker),
        ]
    )
    aspect_value = size[0] / size[1]
    crop_boxes = center_plan(1280, 720, aspect_value, None)["crop_boxes"]
    first_box = crop_boxes[0]
    moving_box = {**first_box, "t": 10.0, "x": first_box["x"] + 20}
    prepared = {"clips": [{"rank": 1, "speaker_path": str(speaker), "crop_boxes": [first_box, moving_box]}]}
    options = {"aspect_ratio": aspect, "captions": True, "caption_style": "bold"}

    result = render_clips(
        {"video_path": str(source)},
        selection,
        timeline,
        prepared,
        transcript,
        tmp_path / "work",
        tmp_path / "out",
        options,
    )

    render = result["renders"][0]
    assert render["status"] == "ready", render.get("error")
    width, height, duration = probe(tmp_path / "out" / "clip-01-test-clip.mp4")
    assert (width, height) == size
    assert abs(duration - 17.4) < 0.5
    assert has_audio(tmp_path / "out" / "clip-01-test-clip.mp4")
    assert (tmp_path / "out" / "clip-01-test-clip.jpg").exists()


def test_crop_filter_interpolates_face_positions():
    result = crop_filter(
        [
            {"t": 0.0, "x": 500, "y": 100, "width": 300, "height": 500},
            {"t": 1.0, "x": 700, "y": 120, "width": 300, "height": 500},
        ],
        1920,
        1080,
        9 / 16,
    )
    assert result.startswith("crop=300:532:")
    assert "if(lt(t\\," in result


def test_source_subtitles_disable_generated_caption_overlay(tmp_path, transcript, monkeypatch):
    source = tmp_path / "source.mp4"
    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=1280x720:rate=30:duration=40",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=40",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-c:a",
            "aac",
            "-shortest",
            str(source),
        ]
    )
    selection = {"clips": [{"rank": 1, "start_seconds": 6.0, "end_seconds": 23.4, "title": "No duplicate"}]}
    timeline = plan_timeline(selection, transcript, broll=False)
    speaker = tmp_path / "work" / "clip-01" / "speaker.mp4"
    speaker.parent.mkdir(parents=True)
    run_ffmpeg(["-ss", "6", "-to", "23.4", "-i", str(source), "-an", "-c:v", "libx264", str(speaker)])
    crop_boxes = center_plan(1280, 720, 9 / 16, None)["crop_boxes"]
    prepared = {"clips": [{"rank": 1, "speaker_path": str(speaker), "crop_boxes": crop_boxes}]}
    work_dir = tmp_path / "work"
    result = render_clips(
        {"video_path": str(source)},
        selection,
        timeline,
        prepared,
        transcript,
        work_dir,
        tmp_path / "out",
        {
            "aspect_ratio": "9:16",
            "captions": True,
            "source_has_subtitles": True,
            "caption_style": "bold",
        },
    )

    assert result["renders"][0]["status"] == "ready"
    assert not (work_dir / "clip-01" / "captions.ass").exists()


def test_render_campaign_montage_from_multiple_sources(tmp_path):
    from clipyyy.render import render_campaign_montages

    sources = []
    for index, colour in enumerate(("red", "blue")):
        source = tmp_path / f"source-{index}.mp4"
        run_ffmpeg(
            [
                "-f",
                "lavfi",
                "-i",
                f"color=c={colour}:s=640x360:r=24:d=12",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-pix_fmt",
                "yuv420p",
                str(source),
            ]
        )
        sources.append({"video_path": str(source), "duration_seconds": 12, "title": f"Source {index}"})
    selection = {
        "campaign_edits": [
            {
                "rank": 1,
                "title": "Multi source test",
                "shots": [
                    {"source_index": 0, "start_seconds": 1, "end_seconds": 4, "reason": "opening"},
                    {"source_index": 1, "start_seconds": 2, "end_seconds": 5, "reason": "build"},
                    {"source_index": 0, "start_seconds": 6, "end_seconds": 9, "reason": "payoff"},
                ],
            }
        ]
    }
    result = render_campaign_montages(
        {"sources": sources},
        selection,
        tmp_path / "work",
        tmp_path / "out",
        {
            "aspect_ratio": "9:16",
            "campaign_lyrics": "\n".join(["First line", "Second line"]),
            "campaign_music_path": None,
            "campaign_plan": {"target_duration_seconds": 9.0, "generated_hook": "Wait for the drop"},
            "include_campaign_hook": True,
        },
    )
    render = result["renders"][0]
    assert render["status"] == "ready", render.get("error")
    width, height, duration = probe(render["file_path"])
    assert (width, height) == (1080, 1920)
    assert 8.0 <= duration <= 9.5
    assert render["lyrics_overlay"] is True
    assert result["quality_checks"]["opening_hook"] == "Wait for the drop"


def test_music_analysis_selects_high_energy_section_and_finds_beats(monkeypatch, tmp_path):
    from array import array
    from types import SimpleNamespace

    from clipyyy import render

    frame = 551
    samples = array("f")
    for index in range(240):
        amplitude = 0.05
        if index >= 60 and (index - 60) % 10 == 0:
            amplitude = 0.9
        samples.extend([amplitude] * frame)
    monkeypatch.setattr(
        render.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout=samples.tobytes(), returncode=0),
    )
    analysis = render.analyze_campaign_music(tmp_path / "track.mp3", 3.0)
    assert analysis["duration_seconds"] == pytest.approx(12.0, abs=0.1)
    assert analysis["best_start_seconds"] >= 2.5
    assert analysis["bpm"] == 120
    assert len(analysis["beat_times"]) >= 4


def test_campaign_lyrics_lrc_timestamps_are_shifted_to_selected_music_section(tmp_path):
    from clipyyy.render import write_campaign_lyrics

    path = write_campaign_lyrics(
        ["[00:10.00]First lyric", "[00:11.50]Second lyric", "[00:25.00]Outside selected section"],
        5.0,
        tmp_path / "timed.ass",
        1080,
        1920,
        offset_seconds=10.0,
    )
    script = path.read_text(encoding="utf-8")
    assert "First lyric" in script
    assert "Second lyric" in script
    assert "Outside selected section" not in script
    assert "0:00:00.00" in script
    assert "\\fscx" in script
    assert "&H00D7FF&" in script


def test_campaign_hook_overlay_is_written(tmp_path):
    from clipyyy.render import write_campaign_hook

    path = write_campaign_hook("Wait for the drop", 2.5, tmp_path / "hook.ass", 1080, 1920)
    assert "Wait for the drop" in path.read_text(encoding="utf-8")


def test_campaign_lyrics_karaoke_style_highlights_words(tmp_path):
    from clipyyy.render import write_campaign_lyrics

    path = write_campaign_lyrics(
        ["[00:00.00]Stay with me tonight"],
        3.0,
        tmp_path / "karaoke.ass",
        1080,
        1920,
        style="karaoke",
    )
    script = path.read_text(encoding="utf-8")
    assert "{\\k" in script
    assert "Stay" in script and "tonight" in script


def test_campaign_word_lyrics_use_recognized_word_timestamps(tmp_path):
    from clipyyy.render import write_campaign_word_lyrics

    path = write_campaign_word_lyrics(
        [
            {"word": "Stay", "start": 2.5, "end": 2.9},
            {"word": "with", "start": 3.0, "end": 3.2},
            {"word": "me", "start": 3.3, "end": 3.8},
        ],
        4.0,
        tmp_path / "word-timed.ass",
        1080,
        1920,
        offset_seconds=2.0,
        style="karaoke",
    )
    script = path.read_text(encoding="utf-8")
    assert "Stay" in script and "with" in script and "me" in script
    assert "{\\k50}Stay" in script
    assert "{\\k30}with" in script
    assert "0:00:00.50" in script
