"""Render a synthetic video end to end with ffmpeg (no network, no models)."""

import pytest

from clipyyy.media import find_ffmpeg, has_audio, probe, run_ffmpeg
from clipyyy.reframe import center_plan
from clipyyy.render import crop_filter, render_clips
from clipyyy.timeline import plan_timeline

pytestmark = pytest.mark.skipif(not find_ffmpeg().ffmpeg, reason="needs ffmpeg")


@pytest.mark.parametrize("normalize_audio", [False, True])
@pytest.mark.parametrize("aspect,size", [("9:16", (1080, 1920)), ("1:1", (1080, 1080))])
def test_render_synthetic_clip(tmp_path, transcript, aspect, size, normalize_audio):
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
    options = {
        "aspect_ratio": aspect,
        "captions": True,
        "caption_style": "bold",
        "normalize_audio": normalize_audio,
    }

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


def test_music_energy_analysis_returns_sections_and_normalized_profile(monkeypatch, tmp_path):
    from array import array
    from types import SimpleNamespace

    from clipyyy import render

    frame = 551
    samples = array("f")
    for index in range(240):
        amplitude = 0.08 if index < 80 else 0.45 if index < 160 else 0.95
        samples.extend([amplitude] * frame)
    monkeypatch.setattr(
        render.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout=samples.tobytes(), returncode=0),
    )

    analysis = render.analyze_campaign_music(tmp_path / "sections.mp3", 5.0)

    assert analysis["energy_profile"]
    assert all(0.0 <= point["energy"] <= 1.0 for point in analysis["energy_profile"])
    assert analysis["energy_sections"]
    assert {section["level"] for section in analysis["energy_sections"]} >= {"low", "high"}


def test_music_cut_selection_prefers_strong_energy_transient_near_target():
    from clipyyy.render import select_music_cut_duration

    analysis = {
        "best_start_seconds": 0.0,
        "beat_times": [3.0, 3.8],
        "beat_strengths": [0.1, 1.0],
        "energy_profile": [
            {"time_seconds": 3.0, "energy": 0.0},
            {"time_seconds": 3.8, "energy": 1.0},
        ],
    }

    assert select_music_cut_duration(0.0, 2.8, analysis) == 3.8


def test_music_cut_selection_falls_back_when_no_transient_is_in_range():
    from clipyyy.render import select_music_cut_duration

    analysis = {
        "best_start_seconds": 0.0,
        "beat_times": [0.8, 1.2, 6.0],
        "beat_strengths": [1.0, 1.0, 1.0],
        "energy_profile": [],
    }

    assert select_music_cut_duration(0.0, 2.5, analysis) is None


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


def test_campaign_word_lyrics_respect_custom_text_and_highlight_colors(tmp_path):
    from clipyyy.render import write_campaign_word_lyrics

    path = tmp_path / "lyrics.ass"
    write_campaign_word_lyrics(
        [{"word": "Hello", "start": 0.0, "end": 0.5}],
        2.0,
        path,
        1080,
        1920,
        style="karaoke",
        text_color="#FF0000",
        highlight_color="#0000FF",
    )
    content = path.read_text(encoding="utf-8")
    assert "&H000000FF" in content
    assert "&H00FF0000" in content


def test_campaign_word_lyrics_apply_both_selected_colors_to_animated_words(tmp_path):
    from clipyyy.render import write_campaign_word_lyrics

    path = tmp_path / "alternating-colors.ass"
    write_campaign_word_lyrics(
        [
            {"word": "Red", "start": 0.0, "end": 0.4},
            {"word": "White", "start": 0.4, "end": 0.8},
            {"word": "Red", "start": 0.8, "end": 1.2},
        ],
        2.0,
        path,
        1080,
        1920,
        style="dynamic",
        text_color="#FF0000",
        highlight_color="#FFFFFF",
    )
    content = path.read_text(encoding="utf-8")
    assert "\\c&H000000FF&" in content
    assert "\\c&H00FFFFFF&" in content


def test_campaign_word_lyrics_karaoke_uses_selected_primary_and_highlight_colors(tmp_path):
    from clipyyy.render import write_campaign_word_lyrics

    path = tmp_path / "custom-karaoke-colors.ass"
    write_campaign_word_lyrics(
        [
            {"word": "Red", "start": 0.0, "end": 0.4},
            {"word": "White", "start": 0.4, "end": 0.8},
        ],
        2.0,
        path,
        1080,
        1920,
        style="karaoke",
        text_color="#FF0000",
        highlight_color="#FFFFFF",
    )
    content = path.read_text(encoding="utf-8")
    assert "\\c&H000000FF&" in content
    assert "\\2c&H00FFFFFF&" in content


def test_campaign_word_lyrics_show_configurable_rolling_word_window(tmp_path):
    from clipyyy.render import write_campaign_word_lyrics

    words = [
        {"word": "One", "start": 0.0, "end": 0.3},
        {"word": "Two", "start": 0.3, "end": 0.6},
        {"word": "Three", "start": 0.6, "end": 0.9},
        {"word": "Four", "start": 0.9, "end": 1.2},
    ]
    three_path = tmp_path / "three-words.ass"
    write_campaign_word_lyrics(words, 2.0, three_path, 1080, 1920, style="dynamic", words_on_screen=3)
    three_events = [
        line for line in three_path.read_text(encoding="utf-8").splitlines() if line.startswith("Dialogue:")
    ]
    assert "One" in three_events[0] and "Two" in three_events[0] and "Three" in three_events[0]
    assert "Four" not in three_events[0]
    assert "Two" in three_events[1] and "Three" in three_events[1] and "Four" in three_events[1]

    two_path = tmp_path / "two-words.ass"
    write_campaign_word_lyrics(words, 2.0, two_path, 1080, 1920, style="dynamic", words_on_screen=2)
    two_events = [
        line for line in two_path.read_text(encoding="utf-8").splitlines() if line.startswith("Dialogue:")
    ]
    assert "One" in two_events[0] and "Two" in two_events[0]
    assert "Three" not in two_events[0]


def test_campaign_audio_filter_uses_custom_music_volume_and_fades():
    from clipyyy.render import _campaign_audio_filter

    audio_filter = _campaign_audio_filter(
        12.0,
        False,
        music_volume=1.25,
        fade_in_seconds=1.2,
        fade_out_seconds=2.5,
    )

    assert audio_filter == "volume=1.250,afade=t=in:st=0:d=1.200,afade=t=out:st=9.500:d=2.500"


def test_campaign_audio_filter_clamps_fades_to_duration_and_allows_no_fades():
    from clipyyy.render import _campaign_audio_filter

    assert _campaign_audio_filter(2.0, False, music_volume=0, fade_in_seconds=5, fade_out_seconds=5) == (
        "volume=0.000,afade=t=in:st=0:d=2.000,afade=t=out:st=0.000:d=2.000"
    )
    assert (
        _campaign_audio_filter(10.0, False, music_volume=1.0, fade_in_seconds=0, fade_out_seconds=0)
        == "volume=1.000"
    )


def test_remove_timed_intervals_keeps_audio_and_video_synchronized(tmp_path):
    from clipyyy.render import remove_timed_intervals

    source = tmp_path / "source.mp4"
    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x240:rate=30:duration=6",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=6",
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
    remove_timed_intervals(source, [(2.0, 3.0)])
    width, height, duration = probe(source)
    assert (width, height) == (320, 240)
    assert duration == pytest.approx(5.0, abs=0.15)
    assert has_audio(source)


def test_campaign_shot_filter_adds_subtle_movement_and_can_disable_it():
    from clipyyy.render import campaign_shot_filter, fill_filter

    moving = campaign_shot_filter(1080, 1920, shot_index=2)
    static = campaign_shot_filter(1080, 1920, shot_index=2, camera_motion=False)

    assert "sin(t*0.32" in moving
    assert "cos(t*0.26" in moving
    assert "eval=frame" in moving
    assert "eq=contrast=1.06:saturation=1.12" in moving
    assert static == fill_filter(1080, 1920) + ",eq=contrast=1.06:saturation=1.12"


def test_campaign_shot_filter_varies_direction_between_shots():
    from clipyyy.render import campaign_shot_filter

    first = campaign_shot_filter(1080, 1920, shot_index=0)
    second = campaign_shot_filter(1080, 1920, shot_index=1)

    assert first != second
    assert "sin(t*0.32+0.0000)" in first
    assert "sin(t*0.32+1.5708)" in second


def test_campaign_transitions_use_the_requested_sequence(tmp_path, monkeypatch):
    from clipyyy import render

    captured = {}

    monkeypatch.setattr(render, "probe", lambda path: (1080, 1920, 2.0))
    monkeypatch.setattr(render, "run_ffmpeg", lambda args: captured.setdefault("args", args))

    render._crossfade_segments(
        [tmp_path / "shot-a.mp4", tmp_path / "shot-b.mp4", tmp_path / "shot-c.mp4"],
        tmp_path / "montage.mp4",
        fade_seconds=0.24,
        transition_names=["smoothleft", "wipeleft"],
    )

    graph = captured["args"][captured["args"].index("-filter_complex") + 1]
    assert "xfade=transition=smoothleft" in graph
    assert "xfade=transition=wipeleft" in graph
    assert "duration=0.24" in graph


def test_campaign_transition_style_defaults_to_auto_and_rejects_unknown_values():
    import pytest

    from clipyyy.pipeline import ClipOptions

    assert ClipOptions().campaign_transition_style == "auto"
    assert ClipOptions(campaign_transition_style="dynamic").campaign_transition_style == "dynamic"
    with pytest.raises(ValueError):
        ClipOptions(campaign_transition_style="flashy")


def test_campaign_word_lyrics_pulse_on_detected_music_beats(tmp_path):
    from clipyyy.render import write_campaign_word_lyrics

    path = tmp_path / "beat-lyrics.ass"
    write_campaign_word_lyrics(
        [{"word": "Hello", "start": 2.0, "end": 2.5}],
        4.0,
        path,
        1080,
        1920,
        offset_seconds=1.0,
        style="dynamic",
        text_color="#FFFFFF",
        highlight_color="#FF3B4F",
        beat_times=[0.8, 2.1, 2.3, 3.5],
    )

    content = path.read_text(encoding="utf-8")
    assert "\\c&H004F3BFF&" in content
    assert "\\t(100,175,\\fscx116\\fscy116)" in content
    assert "\\t(300,375,\\fscx116\\fscy116)" in content
    assert "Hello" in content


def test_campaign_word_lyrics_keep_existing_timing_without_beats(tmp_path):
    from clipyyy.render import write_campaign_word_lyrics

    path = tmp_path / "plain-lyrics.ass"
    write_campaign_word_lyrics(
        [{"word": "Hello", "start": 0.5, "end": 1.0}],
        3.0,
        path,
        1080,
        1920,
        beat_times=[],
    )

    content = path.read_text(encoding="utf-8")
    assert "Dialogue: 0,0:00:00.50" in content
    assert "\\t(0,75,\\fscx116\\fscy116)" not in content


def test_music_cut_selection_prefers_nearby_lyric_phrase_boundary():
    from clipyyy.render import select_music_cut_duration

    analysis = {
        "best_start_seconds": 0.0,
        "beat_times": [3.0, 3.8],
        "beat_strengths": [0.8, 0.8],
        "energy_profile": [],
    }
    cues = [{"text": "Next phrase", "start_seconds": 3.8, "end_seconds": 4.6}]

    # Without lyric timing, the equal-score tie keeps the earlier beat.
    assert select_music_cut_duration(0.0, 3.4, analysis) == 3.0
    # A nearby phrase boundary nudges the cut to the matching transient.
    assert select_music_cut_duration(0.0, 3.4, analysis, cues) == 3.8


def test_music_cut_selection_ignores_malformed_lyric_cues():
    from clipyyy.render import select_music_cut_duration

    analysis = {
        "best_start_seconds": 0.0,
        "beat_times": [3.0, 3.8],
        "beat_strengths": [0.8, 0.8],
        "energy_profile": [],
    }

    assert select_music_cut_duration(0.0, 3.4, analysis, [{"start_seconds": "bad"}]) == 3.0



def test_campaign_shot_filter_uses_tracked_subject_crop_when_available():
    from clipyyy.render import campaign_shot_filter

    crop_boxes = [
        {"t": 0.0, "x": 1000, "y": 100, "width": 600, "height": 1066},
        {"t": 1.0, "x": 1100, "y": 120, "width": 600, "height": 1066},
    ]
    result = campaign_shot_filter(
        1080,
        1920,
        0,
        camera_motion=True,
        crop_boxes=crop_boxes,
        source_width=1920,
        source_height=1080,
    )

    assert result.startswith("crop=600:1066:")
    assert "scale=1080:1920" in result
    assert "sin(t*0.32" not in result


def test_campaign_subject_crop_skips_model_download_when_not_installed(monkeypatch, tmp_path):
    import importlib.util

    import clipyyy.config
    import clipyyy.render as render

    monkeypatch.setattr(clipyyy.config, "home", lambda: tmp_path)
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)

    boxes, width, height = render._campaign_subject_crop(tmp_path / "source.mp4", 0, 4, 9 / 16)

    assert boxes is None
    assert width is None
    assert height is None
