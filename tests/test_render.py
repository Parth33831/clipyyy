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
        run_ffmpeg([
            "-f", "lavfi", "-i", f"color=c={colour}:s=640x360:r=24:d=12",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(source),
        ])
        sources.append({"video_path": str(source), "duration_seconds": 12, "title": f"Source {index}"})
    selection = {
        "campaign_edits": [{
            "rank": 1,
            "title": "Multi source test",
            "shots": [
                {"source_index": 0, "start_seconds": 1, "end_seconds": 4, "reason": "opening"},
                {"source_index": 1, "start_seconds": 2, "end_seconds": 5, "reason": "build"},
                {"source_index": 0, "start_seconds": 6, "end_seconds": 9, "reason": "payoff"},
            ],
        }]
    }
    result = render_campaign_montages(
        {"sources": sources},
        selection,
        tmp_path / "work",
        tmp_path / "out",
        {"aspect_ratio": "9:16", "campaign_lyrics": "First line\\nSecond line", "campaign_music_path": None},
    )
    render = result["renders"][0]
    assert render["status"] == "ready", render.get("error")
    width, height, duration = probe(render["file_path"])
    assert (width, height) == (1080, 1920)
    assert 8.5 <= duration <= 9.5
    assert render["lyrics_overlay"] is True
