from clipyyy.transcribe import group_sentences


def test_group_sentences_splits_at_natural_pauses_without_punctuation():
    words = [
        {"word": "first", "start": 0.0, "end": 0.3},
        {"word": "thought", "start": 0.35, "end": 0.8},
        {"word": "second", "start": 1.9, "end": 2.2},
        {"word": "thought", "start": 2.25, "end": 2.7},
    ]

    sentences = group_sentences(words)

    assert [sentence["text"] for sentence in sentences] == ["first thought", "second thought"]
    assert sentences[0]["end"] == 0.8
    assert sentences[1]["start"] == 1.9


def test_group_sentences_keeps_short_pauses_together():
    words = [
        {"word": "this", "start": 0.0, "end": 0.2},
        {"word": "continues", "start": 0.6, "end": 1.0},
    ]

    assert len(group_sentences(words)) == 1


def test_group_sentences_caps_long_unpunctuated_runs():
    words = [{"word": f"word{i}", "start": i * 0.2, "end": i * 0.2 + 0.1} for i in range(45)]

    sentences = group_sentences(words)

    assert [len(sentence["text"].split()) for sentence in sentences] == [40, 5]
