"""Ask an LLM for strong clips, then snap them to sentence boundaries and validate."""

from __future__ import annotations

import logging
import re
from string import Template
from typing import Any

from clipyyy.config import PACKAGE_DIR
from clipyyy.llm import LLM, LLMError

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
# Small local models produce better results when a long transcript is analysed in focused windows.
# Larger windows reduce the number of serial Ollama calls on CPU-only desktops.
# Keep overlap modest so a moment near a boundary is still visible in both windows.
WINDOW_SECONDS = 18 * 60
WINDOW_OVERLAP_SECONDS = 45
# A short overrun lets a clip finish its final sentence instead of cutting off at the target.
MAX_SENTENCE_OVERRUN_SECONDS = 8.0

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "clips": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "rank": {"type": "integer"},
                    "start_seconds": {"type": "number"},
                    "end_seconds": {"type": "number"},
                    "title": {"type": "string"},
                    "post_title": {"type": "string"},
                    "caption": {"type": "string"},
                    "hashtags": {"type": "array", "items": {"type": "string"}},
                    "broll_queries": {"type": "array", "items": {"type": "string"}},
                    "rationale": {"type": "string"},
                    "hook_score": {"type": "number"},
                    "value_score": {"type": "number"},
                    "clarity_score": {"type": "number"},
                    "overall_score": {"type": "number"},
                },
                "required": [
                    "rank",
                    "start_seconds",
                    "end_seconds",
                    "title",
                    "post_title",
                    "caption",
                    "hashtags",
                    "broll_queries",
                    "rationale",
                    "hook_score",
                    "value_score",
                    "clarity_score",
                    "overall_score",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["clips"],
    "additionalProperties": False,
}


def build_prompt(source: dict, transcript: dict, options: dict) -> tuple[str, str]:
    instructions = (options.get("instructions") or "").strip()
    campaign_brief = (options.get("campaign_brief") or "").strip()
    if options.get("campaign_mode") and campaign_brief:
        instructions = (
            instructions
            + "\n\nCAMPAIGN REQUIREMENTS (highest priority):\n"
            + campaign_brief
            + "\n\nSelect only moments and visuals that directly serve this campaign. Treat the campaign music, subject, mood, language, on-screen text, and platform rules as hard creative constraints. Do not invent campaign requirements or claim a requirement is satisfied unless the output actually satisfies it."
        ).strip()
    template = Template((PACKAGE_DIR / "prompts" / "clip_selection.md").read_text(encoding="utf-8"))
    system = template.substitute(
        clip_count=options["clip_count"],
        min_seconds=_fmt(options["min_seconds"]),
        max_seconds=_fmt(float(options["max_seconds"]) + MAX_SENTENCE_OVERRUN_SECONDS),
        instructions=f"\nInstructions from the user:\n{instructions}\n" if instructions else "",
    )
    lines = "\n".join(f"[{s['start']:.1f}-{s['end']:.1f}] {s['text']}" for s in transcript["sentences"])
    visual_analysis = source.get("visual_analysis") or {}
    visual_notes = visual_analysis.get("frames") or []
    visual_context = ""
    if visual_notes:
        visual_context = "\n\nVISUAL SCENE ANALYSIS (timestamped observations):\n" + "\n".join(
            f"[{frame['timestamp']:.1f}s] {frame['description']} "
            f"(mood: {frame.get('mood', 'unspecified')}; subjects: {frame.get('subjects', 'unspecified')})"
            for frame in visual_notes
        )
    user = (
        f"Video: {source.get('title') or 'Untitled'}"
        + (f" by {source['uploader']}" if source.get("uploader") else "")
        + f" ({source.get('duration_seconds', 0):.0f}s, language: {transcript.get('language')})\n\n"
        f"Transcript (one sentence per line, [start-end] in seconds):\n{lines}\n\n"
        f"Return exactly {options['clip_count']} strong, non-overlapping clips "
        "if the transcript contains enough; return fewer only if it genuinely does not."
        + visual_context
    )
    return system, user


def _windows(sentences: list[dict]) -> list[dict]:
    """Split long transcripts into overlapping time windows while keeping original timestamps."""
    if not sentences:
        return []
    first = min(float(s["start"]) for s in sentences)
    last = max(float(s["end"]) for s in sentences)
    if last - first <= WINDOW_SECONDS:
        return [{"sentences": sentences}]
    windows = []
    cursor = first
    step = WINDOW_SECONDS - WINDOW_OVERLAP_SECONDS
    while cursor < last:
        limit = cursor + WINDOW_SECONDS
        chunk = [s for s in sentences if float(s["end"]) > cursor and float(s["start"]) < limit]
        if chunk:
            windows.append({"sentences": chunk})
        cursor += step
    return windows


def select_clips(llm: LLM, source: dict, transcript: dict, options: dict) -> dict:
    sentences = transcript.get("sentences") or []
    if not sentences:
        raise ValueError("No speech found in the video, so there is nothing to clip")

    windows = _windows(sentences)
    candidates: list[dict] = []
    last_error = "no clips returned"

    # Local CPU inference is expensive, so avoid repeating the same window request.
    # Hosted models retain retries for transient provider errors and malformed output.
    max_attempts = 1 if getattr(getattr(llm, "provider", None), "local", False) else MAX_ATTEMPTS

    # Keep the original single-call path for short videos. For long videos, ask for
    # a small shortlist per focused window, then rank all candidates together.
    for window in windows:
        window_transcript = {**transcript, "sentences": window["sentences"]}
        # Ask each focused window for a small shortlist, not just one pick. A single
        # weak or overlapping local-model suggestion should not leave the whole video
        # with fewer than the requested number of usable clips.
        # Ask each long-video window for one extra candidate as a safety margin.
        # Cross-window overlap and global de-duplication can remove otherwise valid picks,
        # so requesting only the exact per-window share often under-delivers the final count.
        window_count = max(
            2,
            min(3, (int(options["clip_count"]) + len(windows) - 1) // len(windows) + 1),
        )
        window_options = {**options, "clip_count": window_count} if len(windows) > 1 else options
        system, user = build_prompt(source, window_transcript, window_options)
        for attempt in range(1, max_attempts + 1):
            try:
                raw = llm.complete_json(system, user, SCHEMA, "clip_selection").get("clips", [])
            except LLMError as exc:
                last_error = str(exc)
                logger.warning("clip selection attempt %d failed: %s", attempt, exc)
                # A timeout or connection failure cannot be fixed by resending the same
                # expensive local inference request. Stop this window immediately.
                if not getattr(exc, "retryable", True):
                    # A local timeout/connection failure applies to the whole model
                    # service, not just this transcript window. Abort the run instead
                    # of waiting through the remaining windows one by one.
                    raise ValueError(f"Clip selection stopped: {last_error}") from exc
                if attempt == max_attempts:
                    break
                continue
            valid = validate_clips(raw, window_transcript, window_options)
            if valid:
                # Keep only candidates that passed this window's timestamp/length checks.
                for candidate in valid:
                    candidate["overall_score"] = candidate.pop("score", 0.0)
                candidates.extend(valid)
                break
            last_error = "the model did not suggest a clip within the requested length"
            logger.warning("clip selection attempt %d: %s", attempt, last_error)

    if not candidates:
        raise ValueError(f"Clip selection failed: {last_error}")

    # Compare scores across windows so the final clips are the strongest, not merely
    # the first moments returned by the model. validate_clips removes overlaps globally.
    candidates.sort(key=lambda item: _num(item.get("overall_score", item.get("score")), 0.0), reverse=True)
    for rank, candidate in enumerate(candidates, start=1):
        candidate["rank"] = rank
    clips = validate_clips(candidates, transcript, options)

    # Hosted models can cheaply make one focused refill pass when window overlap or
    # duplicate rejection leaves the requested count short. Never repeat expensive
    # CPU-only local inference just to fill a quota.
    is_local = getattr(getattr(llm, "provider", None), "local", False)
    if len(windows) > 1 and len(clips) < int(options["clip_count"]) and not is_local:
        for window in windows:
            remaining = int(options["clip_count"]) - len(clips)
            if remaining <= 0:
                break
            selected = clips
            available = [
                sentence
                for sentence in window["sentences"]
                if not any(
                    float(sentence["start"]) < clip["end_seconds"]
                    and clip["start_seconds"] < float(sentence["end"])
                    for clip in selected
                )
            ]
            if len(available) < 2:
                continue
            refill_transcript = {**transcript, "sentences": available}
            refill_options = {**options, "clip_count": min(remaining, 3)}
            system, user = build_prompt(source, refill_transcript, refill_options)
            user += (
                "\n\nFind additional moments only. Do not reuse or overlap these selected intervals: "
                + ", ".join(f"{clip['start_seconds']:.1f}-{clip['end_seconds']:.1f}s" for clip in selected)
            )
            try:
                raw = llm.complete_json(system, user, SCHEMA, "clip_selection").get("clips", [])
            except LLMError as exc:
                logger.warning("clip selection refill skipped: %s", exc)
                break
            refill = validate_clips(raw, refill_transcript, refill_options)
            for candidate in refill:
                candidate["overall_score"] = candidate.pop("score", 0.0)
            candidates.extend(refill)
            candidates.sort(
                key=lambda item: _num(item.get("overall_score", item.get("score")), 0.0),
                reverse=True,
            )
            clips = validate_clips(candidates, transcript, options)

    return {"model": llm.model, "clips": clips}


def validate_clips(raw_clips: list[dict], transcript: dict, options: dict) -> list[dict]:
    """Snap to sentences, drop clips outside the length range or overlapping a better one."""
    min_s, max_s = float(options["min_seconds"]), float(options["max_seconds"])
    sentences = sorted(transcript["sentences"], key=lambda s: (s["start"], s["end"]))
    accepted: list[dict] = []
    for item in sorted(raw_clips, key=lambda c: _num(c.get("rank"), 999)):
        try:
            start, end = float(item["start_seconds"]), float(item["end_seconds"])
        except (KeyError, TypeError, ValueError):
            continue
        # Reject timestamps outside the actual transcript before snapping. Otherwise
        # an out-of-range suggestion can be pulled back onto unrelated final sentences.
        if start < float(sentences[0]["start"]) or end > float(sentences[-1]["end"]):
            continue
        start, end = snap(start, end, sentences, min_s, max_s)
        if not (min_s - 0.5 <= end - start <= max_s + MAX_SENTENCE_OVERRUN_SECONDS + 0.5):
            continue
        if any(start < c["end_seconds"] and c["start_seconds"] < end for c in accepted):
            continue
        hashtags, caption = clean_hashtags(item.get("hashtags"), str(item.get("caption", "")))
        accepted.append(
            {
                "start_seconds": round(start, 3),
                "end_seconds": round(end, 3),
                "title": str(item.get("title", "")).strip() or f"Clip {len(accepted) + 1}",
                "post_title": str(item.get("post_title", "")).strip()[:100],
                "caption": clean_caption(caption),
                "hashtags": hashtags,
                "broll_queries": [
                    str(q).strip() for q in (item.get("broll_queries") or []) if str(q).strip()
                ][:8],
                "rationale": str(item.get("rationale", "")).strip(),
                "score": _num(item.get("overall_score"), 0.0),
                "transcript": excerpt(start, end, sentences),
            }
        )
        if len(accepted) == options["clip_count"]:
            break
    for rank, clip in enumerate(accepted, start=1):
        clip["rank"] = rank
    return accepted


def snap(start: float, end: float, sentences: list[dict], min_s: float, max_s: float) -> tuple[float, float]:
    """Snap to complete sentences, allowing a brief overrun rather than cutting speech."""
    if not sentences:
        return start, min(max(end, start + min_s), start + max_s)
    start = min(sentences, key=lambda s: abs(s["start"] - start))["start"]
    requested_end = end
    end = min(sentences, key=lambda s: abs(s["end"] - end))["end"]
    if end <= start:
        later = [s["end"] for s in sentences if s["end"] > start]
        end = later[0] if later else start + min_s
    if end - start < min_s:
        longer = [s["end"] for s in sentences if s["end"] >= start + min_s]
        if longer:
            end = min(longer)
        else:
            earlier = [s["start"] for s in sentences if s["start"] <= end - min_s]
            if earlier:
                start = max(earlier)
    # When the model has chosen an endpoint near the target limit, finish the next
    # sentence if its boundary is within the small completion allowance.
    if requested_end - start >= max_s - 3:
        completion = [
            s["end"]
            for s in sentences
            if start + max_s < s["end"] <= start + max_s + MAX_SENTENCE_OVERRUN_SECONDS
        ]
        if completion:
            return start, min(completion)
    if end - start > max_s:
        fitting = [s["end"] for s in sentences if start < s["end"] <= start + max_s]
        if fitting and max(fitting) - start >= min_s:
            end = max(fitting)
        else:
            # No complete sentence fits the requested range; prefer the first
            # complete boundary within the allowance. Validation rejects longer clips.
            completion = [
                s["end"]
                for s in sentences
                if start + max_s < s["end"] <= start + max_s + MAX_SENTENCE_OVERRUN_SECONDS
            ]
            end = min(completion) if completion else end
    return start, end


def excerpt(start: float, end: float, sentences: list[dict]) -> str:
    return " ".join(s["text"] for s in sentences if s["start"] >= start - 0.01 and s["end"] <= end + 0.01)


_LENGTH_MARKER = re.compile(r"\s*\(\d+\s*(?:chars?|characters?|s|secs?|seconds?)\)\s*$", re.IGNORECASE)
_TRAILING_TAGS = re.compile(r"(?:\s*#[\w\u00C0-\uFFFF]+)+\s*$")


def clean_caption(caption: str) -> str:
    value = caption.strip()
    while (updated := _LENGTH_MARKER.sub("", value).strip()) != value:
        value = updated
    return re.sub(r"\s{2,}", " ", value)


def clean_hashtags(tags: Any, caption: str) -> tuple[list[str], str]:
    """Normalise hashtags and move any trailing hashtags out of the caption."""
    found = _TRAILING_TAGS.search(caption)
    extra = found.group(0).split() if found else []
    caption = caption[: found.start()].strip() if found else caption
    result: list[str] = []
    for tag in [*(tags if isinstance(tags, list) else []), *extra]:
        cleaned = "#" + re.sub(r"[^\w\u00C0-\uFFFF]", "", str(tag))
        if len(cleaned) > 1 and cleaned.lower() not in {t.lower() for t in result}:
            result.append(cleaned)
    return result[:10], caption


def _num(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _fmt(value: float) -> str:
    return f"{float(value):g}"
