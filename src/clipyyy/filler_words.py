"""Conservative detection and removal of standalone English hesitation fillers."""

from __future__ import annotations

import re

FILLERS = frozenset({"um", "uh", "erm", "er"})
SAFETY_PADDING = 0.025
MIN_NEIGHBOUR_GAP = 0.015
_TOKEN = re.compile(r"^\W*([a-z]+)\W*$", re.IGNORECASE)


def filler_intervals(
    transcript: dict,
    clip_start: float,
    clip_end: float,
    *,
    language: str,
) -> list[tuple[float, float]]:
    """Return conservative source-time intervals for English fillers in a clip."""
    if language.lower().split("-", 1)[0] != "en":
        return []

    words = transcript.get("words", [])
    intervals: list[tuple[float, float]] = []
    for index, word in enumerate(words):
        match = _TOKEN.fullmatch(str(word.get("word", "")).strip())
        if not match or match.group(1).lower() not in FILLERS:
            continue
        start = float(word.get("start", 0.0))
        end = float(word.get("end", 0.0))
        duration = end - start
        if duration < 0.06 or duration > 0.9:
            continue
        if start < clip_start or end > clip_end or end <= start:
            continue

        # Only remove clearly isolated hesitation tokens. Extend slightly into
        # surrounding silence, but never overlap a neighbouring recognized word.
        previous_end = float(words[index - 1]["end"]) if index else start
        next_start = float(words[index + 1]["start"]) if index + 1 < len(words) else end
        if previous_end > start or next_start < end:
            continue
        cut_start = max(start - SAFETY_PADDING, previous_end + MIN_NEIGHBOUR_GAP)
        cut_end = min(end + SAFETY_PADDING, next_start - MIN_NEIGHBOUR_GAP)
        if cut_end - cut_start >= 0.06:
            intervals.append((round(cut_start, 3), round(cut_end, 3)))
    return intervals
