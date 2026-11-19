from clipyyy.filler_words import filler_intervals


def test_filler_intervals_detect_only_conservative_standalone_english_words():
    transcript = {
        "language": "en",
        "words": [
            {"word": "Well", "start": 0.0, "end": 0.3},
            {"word": "um,", "start": 0.5, "end": 0.8},
            {"word": "I", "start": 1.0, "end": 1.1},
            {"word": "uh.", "start": 1.3, "end": 1.6},
            {"word": "umbrella", "start": 1.8, "end": 2.2},
            {"word": "erm", "start": 2.4, "end": 3.6},
            {"word": "er", "start": 3.8, "end": 3.9},
            {"word": "there", "start": 4.1, "end": 4.4},
        ],
    }
    assert filler_intervals(transcript, 0.0, 5.0, language="en") == [
        (0.4, 0.9),
        (1.2, 1.7),
        (3.7, 4.0),
    ]


def test_filler_removal_is_english_only():
    transcript = {
        "language": "es",
        "words": [{"word": "um", "start": 1.0, "end": 1.2}],
    }
    assert filler_intervals(transcript, 0.0, 3.0, language="es") == []
    assert filler_intervals(transcript, 0.0, 3.0, language="auto") == []


def test_filler_removal_respects_clip_boundaries():
    transcript = {
        "language": "en",
        "words": [{"word": "uh", "start": 1.0, "end": 1.2}],
    }
    assert filler_intervals(transcript, 1.1, 2.0, language="en") == []
