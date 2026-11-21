import pytest

from clipyyy import render
from clipyyy.pipeline import ClipOptions


def test_audio_normalization_is_off_by_default():
    assert ClipOptions().normalize_audio is False


@pytest.mark.parametrize(
    "has_source_audio,normalize_audio,expected",
    [(True, False, False), (True, True, True), (False, True, False)],
)
def test_speaker_render_adds_loudnorm_only_when_requested_and_audio_exists(
    tmp_path, monkeypatch, has_source_audio, normalize_audio, expected
):
    captured = {}
    monkeypatch.setattr(render, "probe", lambda _path: (1280, 720, 30.0))
    monkeypatch.setattr(render, "has_audio", lambda _path: has_source_audio)
    monkeypatch.setattr(render, "run_ffmpeg", lambda args: captured.setdefault("args", args))

    render.render_speaker_only(
        tmp_path / "source.mp4",
        {"start_seconds": 0.0, "end_seconds": 10.0},
        {"crop_boxes": []},
        tmp_path / "work",
        tmp_path / "out.mp4",
        (1080, 1920),
        None,
        normalize_audio,
    )

    args = captured["args"]
    assert ("-af" in args) is expected
    if expected:
        assert args[args.index("-af") + 1] == render.AUDIO_NORMALIZATION_FILTER


def test_campaign_audio_filter_keeps_legacy_mix_when_normalization_is_off():
    audio_filter = render._campaign_audio_filter(12.0, False)

    assert "volume=0.9" in audio_filter
    assert "afade=t=in" in audio_filter
    assert "loudnorm" not in audio_filter


def test_campaign_audio_filter_appends_loudness_normalization_after_fades():
    audio_filter = render._campaign_audio_filter(12.0, True)

    assert audio_filter.endswith(f",{render.AUDIO_NORMALIZATION_FILTER}")
