"""Universal campaign brief understanding and validation.

The model extracts requirements without assigning fixed niche-specific presets. Unknown
requirements remain null/empty; the original brief is always preserved separately.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CampaignPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    campaign_name: str | None = None
    platform: list[str] = Field(default_factory=list)
    content_type: str | None = None
    subject_or_theme: str | None = None
    source_requirements: list[str] = Field(default_factory=list)
    reference_urls: list[str] = Field(default_factory=list)
    mood: list[str] = Field(default_factory=list)
    language: str | None = None
    output_count: int | None = Field(default=None, ge=1, le=10)
    target_duration_seconds: float | None = Field(default=None, ge=1, le=3600)
    aspect_ratio: str | None = None
    audio_mode: str | None = None
    track_or_sound: str | None = None
    official_platform_sound_required: bool | None = None
    on_screen_text_requirements: list[str] = Field(default_factory=list)
    mandatory_content: list[str] = Field(default_factory=list)
    prohibited_content: list[str] = Field(default_factory=list)
    visual_style_and_pacing: list[str] = Field(default_factory=list)
    post_upload_actions: list[str] = Field(default_factory=list)
    performance_eligibility: list[str] = Field(default_factory=list)
    payout_or_submission_caps: list[str] = Field(default_factory=list)
    rights_or_permissions_to_confirm: list[str] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)


PLAN_SCHEMA: dict[str, Any] = CampaignPlan.model_json_schema()
PLAN_SCHEMA["required"] = list(PLAN_SCHEMA["properties"])
PLAN_SCHEMA["additionalProperties"] = False
PLAN_SYSTEM = """You are a universal short-form campaign strategist. Read the supplied campaign
brief and extract its actual requirements into the schema. Do not assume a niche or use fixed
campaign presets. Infer the subject and creative approach from the brief itself. Preserve exact
names and constraints where possible. Do not invent missing values: use null for unknown scalar
values and empty arrays when no items are specified. Separate requirements for the exported video
from actions the creator must perform after uploading, and from performance/eligibility metrics
that can only be checked after publication. List unclear or conflicting requirements as unresolved
questions. Rights/permission concerns should be flagged, never assumed cleared. Return JSON only."""


def parse_campaign_brief(llm, brief: str) -> dict[str, Any]:
    """Return a conservative structured plan; preserve the raw brief outside this object."""
    text = brief.strip()
    if not text:
        return CampaignPlan().model_dump()
    try:
        result = llm.complete_json(
            PLAN_SYSTEM,
            "Extract the requirements from this campaign brief. Do not add assumptions.\n\n" + text,
            PLAN_SCHEMA,
            "campaign_requirements",
        )
        return CampaignPlan.model_validate(result).model_dump()
    except Exception:
        # A small local model may fail to return schema-valid JSON. Keep the original
        # brief in the pipeline and continue conservatively rather than using a cloud API.
        fallback = local_fallback_plan(text)
        fallback["unresolved_questions"].append(
            "The local model could not structure the brief; the original brief remains the source of truth."
        )
        return fallback


def local_fallback_plan(brief: str) -> dict[str, Any]:
    """A transparent fallback for local text-only models; makes no inferred claims."""
    return {
        **CampaignPlan().model_dump(),
        "unresolved_questions": [
            "Structured AI interpretation was skipped for the local text-only model. "
            "The full brief will still guide clip selection."
        ],
    }


HOOK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"hook": {"type": "string"}},
    "required": ["hook"],
    "additionalProperties": False,
}


def generate_campaign_hook(
    llm,
    brief: str,
    campaign_plan: dict[str, Any],
    reference_analyses: list[dict[str, Any]] | None = None,
) -> str | None:
    """Suggest one truthful opening hook using the local text model and campaign context."""
    try:
        result = llm.complete_json(
            "You are a short-form video creative director. Write one original opening hook of 3–8 words. "
            "It must fit the actual creative subject and create curiosity immediately. Never turn a campaign "
            "title into a brand plug: do not include platform, app, company, product, or campaign "
            "names unless "
            "the brief explicitly asks the exported video to promote that named entity. Avoid unsupported "
            "claims, fake urgency, copied slogans, lyrics, hashtags, or claims about live trends. "
            "Do not describe footage you have not seen. Return JSON only.",
            "Campaign brief:\n"
            + brief[:5000]
            + "\n\nCampaign context:\n"
            + json.dumps(
                {
                    "name": campaign_plan.get("campaign_name"),
                    "subject": campaign_plan.get("subject_or_theme"),
                    "mood": campaign_plan.get("mood"),
                    "style": campaign_plan.get("visual_style_and_pacing"),
                    "music": campaign_plan.get("track_or_sound"),
                },
                ensure_ascii=False,
            )
            + "\n\nReference-video style observations (use only broad patterns; never copy wording):\n"
            + json.dumps(reference_analyses or [], ensure_ascii=False)[:3000],
            HOOK_SCHEMA,
            "campaign_opening_hook",
        )
        hook_words = " ".join(str(result.get("hook", "")).split()).strip(" \t\r\n.!?").split()
        return " ".join(hook_words[:8])[:72] or None
    except Exception:
        return None


MONTAGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "edits": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "shots": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "source_index": {"type": "integer"},
                                "start_seconds": {"type": "number"},
                                "end_seconds": {"type": "number"},
                                "reason": {"type": "string"},
                            },
                            "required": ["source_index", "start_seconds", "end_seconds", "reason"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["title", "shots"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["edits"],
    "additionalProperties": False,
}


def _intersects_black_interval(
    start: float, end: float, intervals: list[list[float] | tuple[float, float]]
) -> bool:
    """Check a candidate point or shot range against detected near-black footage."""
    for interval in intervals:
        try:
            black_start, black_end = float(interval[0]), float(interval[1])
        except (TypeError, ValueError, IndexError):
            continue
        if start == end:
            overlaps = black_start <= start <= black_end
        else:
            overlaps = black_start < end and black_end > start
        if overlaps:
            return True
    return False


_LYRIC_MATCH_STOPWORDS = {
    "about",
    "after",
    "again",
    "against",
    "all",
    "and",
    "are",
    "around",
    "because",
    "been",
    "before",
    "being",
    "between",
    "but",
    "can",
    "could",
    "did",
    "does",
    "down",
    "each",
    "for",
    "from",
    "get",
    "got",
    "had",
    "has",
    "have",
    "her",
    "here",
    "him",
    "his",
    "how",
    "into",
    "its",
    "just",
    "like",
    "make",
    "more",
    "most",
    "not",
    "now",
    "our",
    "out",
    "over",
    "same",
    "she",
    "should",
    "some",
    "than",
    "that",
    "the",
    "their",
    "them",
    "then",
    "there",
    "these",
    "they",
    "this",
    "those",
    "through",
    "too",
    "under",
    "was",
    "were",
    "what",
    "when",
    "where",
    "which",
    "who",
    "will",
    "with",
    "would",
    "you",
    "your",
}


def _rank_lyric_scene_matches(
    lyric_cues: list[dict[str, Any]], candidates: list[dict[str, Any]], limit: int = 3
) -> list[dict[str, Any]]:
    """Return transparent lexical evidence links between timed lyrics and real scene observations.

    This is a candidate hint, not a claim of semantic understanding or source/music time alignment.
    The LLM still interprets the campaign story; unmatched cues deliberately receive no forced shot.
    """
    matches = []
    for cue in lyric_cues[:80]:
        text = " ".join(str(cue.get("text") or "").split()).strip()
        cue_tokens = {
            token
            for token in re.findall(r"[a-z0-9']+", text.lower())
            if len(token) > 2 and token not in _LYRIC_MATCH_STOPWORDS
        }
        if not text or not cue_tokens:
            continue
        ranked = []
        for frame in candidates:
            description = str(frame.get("description") or "")
            if "Visual content unavailable" in description:
                continue
            evidence_parts = [
                str(frame.get("description") or ""),
                str(frame.get("visible_action") or ""),
                str(frame.get("visible_text") or ""),
                str(frame.get("subjects") or ""),
                str(frame.get("mood") or ""),
            ]
            scene_tokens = {
                token
                for token in re.findall(r"[a-z0-9']+", " ".join(evidence_parts).lower())
                if len(token) > 2 and token not in _LYRIC_MATCH_STOPWORDS
            }
            matched = cue_tokens & scene_tokens
            if not matched:
                continue
            try:
                confidence = float(frame.get("confidence", 0.5))
            except (TypeError, ValueError):
                confidence = 0.5
            confidence = max(0.0, min(1.0, confidence))
            coverage = len(matched) / len(cue_tokens)
            score = coverage * (0.5 + 0.5 * confidence)
            if score < 0.15:
                continue
            ranked.append(
                {
                    "source_index": frame.get("source_index"),
                    "source_title": frame.get("source_title"),
                    "source_timestamp": round(float(frame.get("timestamp", 0.0)), 3),
                    "score": round(score, 3),
                    "matched_terms": sorted(matched),
                    "visual_evidence": description[:220],
                    "visible_action": str(frame.get("visible_action") or "unknown")[:160],
                }
            )
        ranked.sort(key=lambda item: (-item["score"], item["source_index"], item["source_timestamp"]))
        try:
            start = round(float(cue.get("start_seconds")), 3)
            end = round(float(cue.get("end_seconds")), 3)
        except (TypeError, ValueError):
            start = end = None
        matches.append(
            {
                "cue_text": text[:160],
                "cue_start_seconds": start,
                "cue_end_seconds": end,
                "matches": ranked[:limit],
            }
        )
    return matches


_VISUAL_ENERGY_CUES = {
    "high": (
        r"\b(sprint(?:ing)?|run(?:ning)?|jump(?:ing)?|dance|dancing|"
        r"fight(?:ing)?|chase|chasing|explod(?:e|es|ing)|crash(?:ing)?|"
        r"slam(?:ming)?|racing|rapid(?:ly)?|fast[- ]paced|"
        r"cheer(?:ing)?|celebrat(?:e|ing)|perform(?:ing)?|"
        r"workout|exercise|action[- ]packed)\b"
    ),
    "medium": (
        r"\b(walk(?:ing)?|talk(?:ing)?|speaking|working|build(?:ing)?|"
        r"cook(?:ing)?|typing|driv(?:ing)?|mov(?:e|ing)|"
        r"demonstrat(?:e|ing)|present(?:ing)?|interact(?:ing)?|"
        r"playing|creating|showing)\b"
    ),
    "low": (
        r"\b(still|calm|peaceful|quiet|rest(?:ing)?|"
        r"meditat(?:e|ing)|sleep(?:ing)?|sunset|sunrise|"
        r"landscape|scenic|slow[- ]motion|reflective)\b"
    ),
}


def _annotate_scene_music_matches(
    candidates: list[dict[str, Any]],
    music_analysis: dict[str, Any] | None,
    target_seconds: float,
) -> None:
    """Attach evidence-based visual-energy hints and matching windows in the selected music section.

    Source-video timestamps are never treated as music timestamps. Only the visual action
    classification is matched to the independent, selected music energy-section clock.
    Unknown visual energy remains unknown rather than being guessed.
    """
    if not music_analysis:
        return
    try:
        music_start = max(0.0, float(music_analysis.get("best_start_seconds") or 0.0))
        music_end = music_start + max(0.0, float(target_seconds))
    except (TypeError, ValueError):
        return
    sections = []
    for section in music_analysis.get("energy_sections") or []:
        try:
            start = float(section.get("start_seconds", 0.0))
            end = float(section.get("end_seconds", start))
            energy = float(section.get("average_energy", 0.5))
        except (TypeError, ValueError):
            continue
        if end <= music_start or start >= music_end:
            continue
        level = str(section.get("level") or "")
        if level not in {"low", "medium", "high"}:
            level = "low" if energy < 0.34 else "medium" if energy < 0.68 else "high"
        sections.append(
            {
                "start_seconds": round(max(start, music_start), 3),
                "end_seconds": round(min(end, music_end), 3),
                "level": level,
                "average_energy": round(max(0.0, min(1.0, energy)), 3),
            }
        )
    for candidate in candidates:
        evidence_text = " ".join(
            str(candidate.get(field) or "") for field in ("description", "visible_action", "mood")
        ).lower()
        try:
            confidence = max(0.0, min(1.0, float(candidate.get("confidence", 0.5))))
        except (TypeError, ValueError):
            confidence = 0.5
        visual_level = "unknown"
        evidence = []
        if confidence >= 0.25:
            for level in ("high", "low", "medium"):
                matches = re.findall(_VISUAL_ENERGY_CUES[level], evidence_text, flags=re.IGNORECASE)
                if matches:
                    visual_level = level
                    evidence = sorted({str(match).lower() for match in matches})[:3]
                    break
        matching_sections = (
            [section for section in sections if section["level"] == visual_level]
            if visual_level != "unknown"
            else []
        )
        matching_sections.sort(
            key=lambda section: (
                -section["average_energy"]
                if visual_level == "high"
                else section["average_energy"]
                if visual_level == "low"
                else abs(section["average_energy"] - 0.5),
                section["start_seconds"],
            )
        )
        candidate["music_alignment"] = {
            "visual_energy": visual_level,
            "evidence": evidence,
            "confidence": round(confidence, 2),
            "matching_music_windows": matching_sections[:3],
        }


def build_montage_plan(
    llm,
    brief: str,
    campaign_plan: dict[str, Any],
    sources: list[dict],
    analyses: list[dict],
    output_count: int,
    target_seconds: float,
    additional_instructions: str = "",
    reference_analyses: list[dict] | None = None,
    music_analysis: dict[str, Any] | None = None,
    campaign_lyrics: str = "",
    lyric_cues: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Choose an ordered montage from timestamped visual observations across all sources."""
    if not hasattr(llm, "complete_json"):
        raise ValueError("The selected AI model cannot create a structured montage plan.")
    candidates = []
    for source_index, (source, analysis) in enumerate(zip(sources, analyses, strict=True)):
        black_intervals = analysis.get("black_intervals", [])
        for frame in analysis.get("frames", []):
            try:
                timestamp = float(frame["timestamp"])
            except (KeyError, TypeError, ValueError):
                continue
            if _intersects_black_interval(timestamp, timestamp, black_intervals):
                continue
            candidates.append(
                {
                    "source_index": source_index,
                    "source_title": source.get("title", f"Source {source_index + 1}"),
                    "source_duration": float(source.get("duration_seconds") or 0),
                    **frame,
                }
            )
    _annotate_scene_music_matches(candidates, music_analysis, target_seconds)
    # Text-only local models cannot inspect sampled frames. Never treat placeholder
    # observations as real visual descriptions; use an explicitly generic timestamp spread.
    text_only_frames = bool(candidates) and all(
        "Visual content unavailable" in str(item.get("description", "")) for item in candidates
    )
    if candidates and text_only_frames:
        return _build_text_only_montage(sources, output_count, target_seconds, analyses)
    lyric_scene_matches = _rank_lyric_scene_matches(lyric_cues or [], candidates)
    if len(candidates) < 3:
        raise ValueError(
            "Not enough visual scenes could be analysed. Use a vision-capable model and clear source videos."
        )
    system = (
        "You are an expert campaign film editor and visual storyteller. First infer the campaign's actual "
        "message, audience and intended emotional response from the brief; do not assume a product-launch, "
        "testimonial or other fixed template. Shape each edit as a clear, purposeful mini-story. When the "
        "available footage supports it, move from an attention-grabbing opening, to context or need, to a "
        "visual build or demonstration, to a credible payoff. Use a call to action only when the brief asks "
        "for one and the supplied footage or required on-screen text can support it. These are flexible "
        "story functions, not mandatory beats: omit or adapt any beat that the footage cannot honestly show. "
        "Use only supplied source indexes, observations and actual source durations. Prioritize mandatory "
        "campaign content and relevance to the brief; reject visually attractive but irrelevant shots. "
        "Use creator footage as the narrative backbone and stock footage only as supporting coverage when "
        "it genuinely helps explain or connect the story. Seek visual variety in framing, subjects, mood and "
        "source without sacrificing relevance or continuity. "
        "Avoid repeated moments and abrupt semantic jumps. "
        "Use shot_scale, visible_action, visible_text and confidence as additional evidence "
        "alongside each frame description, mood and subjects. Prefer high-confidence observations when "
        "they improve relevance; treat unknown or low-confidence attributes as uncertain, not as facts. "
        "Choose shot variety deliberately, such as alternating wide context with close-up detail when "
        "the brief benefits. "
        "Each shot should be 2 to 5 seconds and its reason must briefly explain both its observed relevance "
        "and its role in the story. Never invent unseen events, dialogue, lyrics, product features, results, "
        "testimonials or rights permissions. Respect prohibited content and unresolved requirements. "
        "Return JSON only."
    )
    music_guidance = ""
    if music_analysis:
        beats = music_analysis.get("beat_times") or []
        strengths = music_analysis.get("beat_strengths") or []
        strongest = sorted(
            (
                (float(strengths[index]) if index < len(strengths) else 0.0, float(timestamp))
                for index, timestamp in enumerate(beats)
            ),
            reverse=True,
        )[:12]
        music_guidance = (
            "\n\nMUSICAL STRUCTURE (detected from the creator-provided track; timestamps are seconds):\n"
            + json.dumps(
                {
                    "estimated_bpm": music_analysis.get("bpm"),
                    "selected_section": music_analysis.get("selected_section"),
                    "beat_interval_seconds": music_analysis.get("beat_interval_seconds"),
                    "strong_transients_seconds": [
                        round(timestamp, 3) for _, timestamp in sorted(strongest, key=lambda item: item[1])
                    ],
                    "energy_sections": music_analysis.get("energy_sections", [])[:16],
                },
                ensure_ascii=False,
            )
            + "\nPlan the visual rhythm around this structure: use calmer/longer relevant shots in "
            "low-energy passages, build visual momentum as energy rises, and reserve the strongest relevant "
            "footage or visual payoff for high-energy peaks and major transients. Prefer cut points near "
            "strong beats when the footage supports it. Do not sacrifice campaign relevance, shot quality, "
            "continuity, or truthful storytelling just to hit a beat. The renderer will refine cut timing "
            "to nearby detected transients; choose the right visual moments first."
        )
    lyric_guidance = ""
    supplied_lyrics = "\n".join(
        line.strip() for line in str(campaign_lyrics or "").splitlines() if line.strip()
    )
    if supplied_lyrics:
        lyric_guidance = (
            "\n\nCREATOR-SUPPLIED CAMPAIGN LYRICS (meaning reference only; no word timestamps supplied):\n"
            + supplied_lyrics[:6000]
            + "\nUse these lyrics as an optional semantic/storytelling cue. Match a lyric idea to a shot "
            "only when the supplied visual observations genuinely support that meaning. Do not invent "
            "visuals to illustrate a lyric, do not assume the lyric is sung at a particular timestamp, "
            "and do not force a literal illustration. If no observed shot supports a lyric, prioritize "
            "the campaign brief and truthful visual continuity instead."
        )
    timed_lyric_guidance = ""
    if lyric_cues:
        timed_lyric_guidance = (
            "\n\nTIMED LYRIC CUES (seconds relative to the selected music segment):\n"
            + json.dumps(lyric_cues[:80], ensure_ascii=False)
            + "\nUse the cue order and approximate timing to shape the visual progression. "
            "A cue timestamp refers to the music, not to a source video's timestamp. "
            "The shot-plan format does not express exact overlay positions, so do not claim "
            "frame-accurate lyric-to-shot synchronization. Prefer visual moments whose observed "
            "meaning supports the lyric progression, and preserve campaign relevance."
        )
    lyric_match_guidance = ""
    if lyric_scene_matches:
        lyric_match_guidance = (
            "\n\nLYRIC-TO-SCENE EVIDENCE HINTS (lexical overlap only; not semantic proof):\n"
            + json.dumps(lyric_scene_matches, ensure_ascii=False)
            + "\nUse a listed scene only when its actual visual evidence supports the cue and the campaign "
            "story. Scores represent literal keyword overlap adjusted by observation confidence, not model "
            "certainty. An empty match list means no direct wording evidence was found; do not "
            "invent a match. Cue times are relative to the music segment and source timestamps are "
            "relative to source videos; "
            "they are different clocks and must not be compared as if they were aligned.\n"
        )
    user = (
        f"Campaign brief:\n{brief}\n\nExtracted requirements:\n"
        f"{format_campaign_plan(campaign_plan)}"
        f"{music_guidance}"
        f"{lyric_guidance}"
        f"{timed_lyric_guidance}"
        f"{lyric_match_guidance}"
        f"\n\nAdditional creator instructions:\n{additional_instructions or 'None'}"
        f"\n\nCreate {output_count} distinct edits, each approximately "
        f"{target_seconds:.1f} seconds. "
        "Choose enough shots to approach the target duration. Every source_index is zero-based. "
        "All timestamps must remain inside the source duration. Use reference observations only "
        "to guide style, pacing, framing and text treatment; never copy reference footage. "
        "For each shot, explain its story function and the visible evidence that makes it relevant. "
        "Make the opening understandable without prior context, create progression rather than a random "
        "highlight reel, and finish on the strongest truthful payoff available. Do not force a CTA, proof "
        "or product shot when none is supported by the brief and observations. "
        "If multiple edits are requested, give each a distinct angle or emotional emphasis while still "
        "meeting the same campaign requirements. "
        "Use the supplied shot_scale, visible_action, visible_text and confidence fields as evidence. "
        "Treat low-confidence or unknown attributes as uncertain, not facts. "
        "When music_alignment is present, use its visual-energy label and matched music windows "
        "to place calm scenes in low-energy passages, active scenes in high-energy passages, and "
        "moderate scenes in medium-energy passages. These are evidence-based pacing hints, not "
        "hard constraints: campaign meaning, visual quality and continuity always take priority. "
        "Never compare source-video timestamps with music timestamps.\n\n"
        "Visual observations from supplied source footage:\n"
        + json.dumps(candidates, ensure_ascii=False)
        + "\n\nVisual observations from reference videos (style guidance only):\n"
        + json.dumps(reference_analyses or [], ensure_ascii=False)
    )
    result = llm.complete_json(system, user, MONTAGE_SCHEMA, "campaign_montage_plan")
    edits = result.get("edits", [])
    valid_edits = []
    for rank, edit in enumerate(edits[:output_count], start=1):
        shots = []
        for shot in edit.get("shots", []):
            try:
                source_index = int(shot["source_index"])
                if not 0 <= source_index < len(sources):
                    continue
                duration = float(sources[source_index].get("duration_seconds") or 0)
                start = max(0.0, min(float(shot["start_seconds"]), duration))
                end = max(start, min(float(shot["end_seconds"]), duration))
                if end - start > 5.0:
                    end = start + 5.0
                if end - start < 1.5:
                    continue
                source_analysis = analyses[source_index] if source_index < len(analyses) else {}
                if _intersects_black_interval(start, end, source_analysis.get("black_intervals", [])):
                    continue
                shots.append(
                    {
                        "source_index": source_index,
                        "start_seconds": round(start, 3),
                        "end_seconds": round(end, 3),
                        "reason": str(shot.get("reason", ""))[:300],
                    }
                )
            except (KeyError, TypeError, ValueError):
                continue
        total = sum(shot["end_seconds"] - shot["start_seconds"] for shot in shots)
        minimum_duration = max(5.0, target_seconds * 0.65)
        if len(shots) >= 3 and total >= minimum_duration:
            if total > target_seconds:
                excess = total - target_seconds
                for shot in reversed(shots):
                    available = shot["end_seconds"] - shot["start_seconds"] - 1.5
                    trim = min(excess, max(0.0, available))
                    shot["end_seconds"] = round(shot["end_seconds"] - trim, 3)
                    excess -= trim
                    if excess <= 0:
                        break
                shots = [shot for shot in shots if shot["end_seconds"] - shot["start_seconds"] >= 1.5]
            valid_edits.append(
                {
                    "rank": rank,
                    "title": str(edit.get("title") or f"Campaign edit {rank}")[:100],
                    "shots": shots,
                }
            )
    if len(valid_edits) < output_count:
        raise ValueError(
            f"The AI produced {len(valid_edits)} valid edits, but the campaign requests {output_count}. "
            "Try more source footage or a shorter target duration."
        )
    return valid_edits


def _build_text_only_montage(
    sources: list[dict],
    output_count: int,
    target_seconds: float,
    analyses: list[dict] | None = None,
) -> list[dict[str, Any]]:
    """Build varied edits around detected scene boundaries without claiming visual understanding."""
    usable = [
        (i, float(source.get("duration_seconds") or 0))
        for i, source in enumerate(sources)
        if float(source.get("duration_seconds") or 0) >= 2.0
    ]
    creator_indexes = {index for index, source in enumerate(sources) if source.get("source_kind") != "pexels"}
    stock_indexes = {index for index, source in enumerate(sources) if source.get("source_kind") == "pexels"}
    if not usable:
        raise ValueError("No usable source footage is available for a text-only montage.")

    candidates: list[tuple[int, float, bool]] = []
    for source_index, duration in usable:
        frames = analyses[source_index].get("frames", []) if analyses and source_index < len(analyses) else []
        black_intervals = (
            analyses[source_index].get("black_intervals", [])
            if analyses and source_index < len(analyses)
            else []
        )
        for frame in frames:
            try:
                timestamp = float(frame["timestamp"])
            except (KeyError, TypeError, ValueError):
                continue
            if 0.25 < timestamp < duration - 1.0 and not _intersects_black_interval(
                timestamp, timestamp, black_intervals
            ):
                candidates.append((source_index, timestamp, True))

    shot_count = max(5, min(24, round(target_seconds / 2.5)))
    required_candidates = shot_count * max(1, output_count)
    # Sparse cuts are supplemented with clearly identified time samples so short or static
    # footage can still render instead of failing after scene detection.
    if len(candidates) < required_candidates:
        per_source = max(24, (required_candidates + len(usable) - 1) // len(usable) + 8)
        existing = {(source_index, round(timestamp, 1)) for source_index, timestamp, _ in candidates}
        for source_index, duration in usable:
            black_intervals = (
                analyses[source_index].get("black_intervals", [])
                if analyses and source_index < len(analyses)
                else []
            )
            for index in range(1, per_source + 1):
                timestamp = duration * index / (per_source + 1)
                key = (source_index, round(timestamp, 1))
                if key not in existing and not _intersects_black_interval(
                    timestamp, timestamp, black_intervals
                ):
                    candidates.append((source_index, timestamp, False))
                    existing.add(key)
    candidates.sort(key=lambda item: (item[0], item[1]))

    # Crossfades shorten the assembled timeline; include their overlap in source footage.
    source_time_needed = target_seconds + 0.28 * (shot_count - 1)
    pattern = [1.9, 2.5, 2.1, 2.9, 2.2, 2.6]
    weights = [pattern[index % len(pattern)] for index in range(shot_count)]
    scale = source_time_needed / sum(weights)
    shot_lengths = [weight * scale for weight in weights]
    if max(shot_lengths) > 4.0 or min(shot_lengths) < 1.25:
        shot_lengths = [source_time_needed / shot_count] * shot_count

    edits = []
    segment_size = max(shot_count, len(candidates) // max(1, output_count))
    for rank in range(1, output_count + 1):
        shots = []
        used: set[tuple[int, int]] = set()
        segment_start = (rank - 1) * segment_size
        segment_end = (
            len(candidates) if rank == output_count else min(len(candidates), segment_start + segment_size)
        )
        segment_candidates = candidates[segment_start:segment_end]
        for index, shot_length in enumerate(shot_lengths):
            preferred_indexes = stock_indexes if stock_indexes and index % 4 == 2 else creator_indexes
            preferred_candidates = [
                candidate for candidate in segment_candidates if candidate[0] in preferred_indexes
            ]
            if not preferred_candidates:
                preferred_candidates = [
                    candidate for candidate in candidates if candidate[0] in preferred_indexes
                ]
            candidate_pool = preferred_candidates or segment_candidates

            def is_usable(candidate: tuple[int, float, bool], shot_duration: float = shot_length) -> bool:
                candidate_source, candidate_time, _ = candidate
                candidate_duration = float(sources[candidate_source].get("duration_seconds") or 0)
                candidate_start = min(
                    max(0.0, candidate_time + 0.06),
                    max(0.0, candidate_duration - shot_duration),
                )
                candidate_end = min(candidate_duration, candidate_start + shot_duration)
                source_analysis = (
                    analyses[candidate_source] if analyses and candidate_source < len(analyses) else {}
                )
                return candidate_end - candidate_start >= 1.25 and not _intersects_black_interval(
                    candidate_start, candidate_end, source_analysis.get("black_intervals", [])
                )

            candidate_pool = [candidate for candidate in candidate_pool if is_usable(candidate)]
            if not candidate_pool:
                candidate_pool = [
                    candidate
                    for candidate in candidates
                    if candidate[0] in preferred_indexes and is_usable(candidate)
                ]
            if not candidate_pool:
                candidate_pool = [candidate for candidate in candidates if is_usable(candidate)]
            if not candidate_pool:
                continue
            candidate_index = min(
                len(candidate_pool) - 1,
                int((index + 0.5) * len(candidate_pool) / shot_count),
            )
            source_index, timestamp, is_scene_change = candidate_pool[candidate_index]
            duration = float(sources[source_index].get("duration_seconds") or 0)
            start = min(max(0.0, timestamp + 0.06), max(0.0, duration - shot_length))
            end = min(duration, start + shot_length)
            key = (source_index, round(start / 1.5))
            if key in used:
                for alt_source, alt_timestamp, alt_is_scene_change in candidate_pool:
                    alt_duration = float(sources[alt_source].get("duration_seconds") or 0)
                    alt_start = min(max(0.0, alt_timestamp + 0.06), max(0.0, alt_duration - shot_length))
                    alt_end = min(alt_duration, alt_start + shot_length)
                    alt_analysis = analyses[alt_source] if analyses and alt_source < len(analyses) else {}
                    alt_key = (alt_source, round(alt_start / 1.5))
                    if alt_key not in used and not _intersects_black_interval(
                        alt_start, alt_end, alt_analysis.get("black_intervals", [])
                    ):
                        source_index, duration, start = alt_source, alt_duration, alt_start
                        end = alt_end
                        key, is_scene_change = alt_key, alt_is_scene_change
                        break
            if end - start >= 1.25 and key not in used:
                used.add(key)
                if sources[source_index].get("source_kind") == "pexels":
                    query = str(sources[source_index].get("search_query") or "campaign")
                    reason = (
                        f"Supporting Pexels footage returned for campaign search '{query}'; "
                        "the text-only model did not inspect the scene."
                    )
                else:
                    reason = (
                        "Selected near an FFmpeg-detected scene change; "
                        "semantic scene content was not analysed."
                        if is_scene_change
                        else (
                            "Fallback time sample; scene semantics were not analysed by the text-only model."
                        )
                    )
                shots.append(
                    {
                        "source_index": source_index,
                        "start_seconds": round(start, 3),
                        "end_seconds": round(end, 3),
                        "reason": reason,
                    }
                )
        if len(shots) < 3:
            raise ValueError("Not enough distinct footage windows were available for a varied montage.")
        edits.append({"rank": rank, "title": f"Campaign montage {rank}", "shots": shots})
    return edits


def format_campaign_plan(plan: dict[str, Any]) -> str:
    """Compact, explicit plan for downstream creative selection."""
    labels = {
        "campaign_name": "Campaign",
        "platform": "Platform",
        "content_type": "Content type",
        "subject_or_theme": "Subject/theme",
        "source_requirements": "Source requirements",
        "reference_urls": "Discovered reference URLs",
        "mood": "Mood",
        "language": "Language",
        "output_count": "Output count",
        "target_duration_seconds": "Target duration (seconds)",
        "aspect_ratio": "Aspect ratio",
        "audio_mode": "Audio mode",
        "track_or_sound": "Track/sound",
        "official_platform_sound_required": "Official platform sound required",
        "on_screen_text_requirements": "On-screen text",
        "mandatory_content": "Mandatory",
        "prohibited_content": "Prohibited",
        "visual_style_and_pacing": "Visual style and pacing",
        "post_upload_actions": "Post-upload actions (manual)",
        "performance_eligibility": "Post-publication eligibility",
        "payout_or_submission_caps": "Payout/submission caps",
        "rights_or_permissions_to_confirm": "Rights/permissions to confirm",
        "unresolved_questions": "Unresolved",
    }
    lines = []
    for key, label in labels.items():
        value = plan.get(key)
        if value is not None and value != []:
            display = ", ".join(map(str, value)) if isinstance(value, list) else value
            lines.append(f"- {label}: {display}")
    if lines:
        return "\n".join(lines)
    return "- No structured requirements extracted; follow the original brief exactly."
