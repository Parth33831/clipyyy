from pathlib import Path

import pytest
from pydantic import ValidationError

from clipyyy.pipeline import CampaignLyricPhrase
from clipyyy.render import write_campaign_phrase_lyrics


def test_campaign_lyric_phrase_requires_positive_time_range():
    with pytest.raises(ValidationError):
        CampaignLyricPhrase(
            id="bad",
            text="No duration",
            start_seconds=3.0,
            end_seconds=3.0,
        )


def test_campaign_phrase_renderer_keeps_individual_timing_and_transforms(tmp_path: Path):
    path = write_campaign_phrase_lyrics(
        [
            {
                "id": "first",
                "text": "First phrase",
                "start_seconds": 2.0,
                "end_seconds": 3.0,
                "position_x": 10,
                "position_y": 20,
                "scale_percent": 120,
                "rotation_degrees": 5,
                "animation": "zoom",
            },
            {
                "id": "second",
                "text": "Second phrase",
                "start_seconds": 4.0,
                "end_seconds": 5.0,
                "position_x": 90,
                "position_y": 80,
                "scale_percent": 80,
                "rotation_degrees": -7,
                "animation": "cinematic",
            },
        ],
        8.0,
        tmp_path / "phrases.ass",
        1080,
        1920,
        offset_seconds=1.0,
    )

    script = path.read_text(encoding="utf-8")
    assert "Dialogue: 0,0:00:01.00,0:00:02.00" in script
    assert "Dialogue: 0,0:00:03.00,0:00:04.00" in script
    assert "First phrase" in script and "Second phrase" in script
    assert r"\pos(108,384)\fscx120\fscy120\frz5" in script
    assert r"\pos(972,1536)\fscx80\fscy80\frz-7" in script
    assert r"\fscx55\fscy55" in script
