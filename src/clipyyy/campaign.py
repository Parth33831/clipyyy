"""Universal campaign brief understanding and validation.

The model extracts requirements without assigning fixed niche-specific presets. Unknown
requirements remain null/empty; the original brief is always preserved separately.
"""

from __future__ import annotations

import json
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
) -> list[dict[str, Any]]:
    """Choose an ordered montage from timestamped visual observations across all sources."""
    if not hasattr(llm, "complete_json"):
        raise ValueError("The selected AI model cannot create a structured montage plan.")
    candidates = []
    for source_index, (source, analysis) in enumerate(zip(sources, analyses, strict=True)):
        for frame in analysis.get("frames", []):
            candidates.append(
                {
                    "source_index": source_index,
                    "source_title": source.get("title", f"Source {source_index + 1}"),
                    "source_duration": float(source.get("duration_seconds") or 0),
                    **frame,
                }
            )
    # Text-only local models cannot inspect sampled frames. Never treat placeholder
    # observations as real visual descriptions; use an explicitly generic timestamp spread.
    text_only_frames = all(
        "Visual content unavailable" in str(item.get("description", "")) for item in candidates
    )
    if candidates and text_only_frames:
        return _build_text_only_montage(sources, output_count, target_seconds, analyses)
    if len(candidates) < 3:
        raise ValueError(
            "Not enough visual scenes could be analysed. Use a vision-capable model and clear source videos."
        )
    system = (
        "You are an expert campaign film editor. Build coherent, emotionally paced short-form video montages "
        "from the supplied timestamped visual observations. Use only supplied source indexes and actual "
        "source durations. Select visually relevant, varied moments; order them into a beginning, build and "
        "payoff. Each shot should be 2 to 5 seconds, avoid repeating the same timestamp, and choose moments "
        "whose surrounding footage is likely to contain the described scene. Never invent unseen events, "
        "dialogue, lyrics or rights permissions. Respect the campaign brief and extracted requirements. "
        "Return JSON only."
    )
    user = (
        f"Campaign brief:\n{brief}\n\nExtracted requirements:\n"
        f"{format_campaign_plan(campaign_plan)}"
        f"\n\nAdditional creator instructions:\n{additional_instructions or 'None'}"
        f"\n\nCreate {output_count} distinct edits, each approximately "
        f"{target_seconds:.1f} seconds. "
        "Choose enough shots to approach the target duration. Every source_index is zero-based. "
        "All timestamps must remain inside the source duration. Use reference observations only "
        "to guide style, pacing, framing and text treatment; never copy reference footage.\n\n"
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
    if not usable:
        raise ValueError("No usable source footage is available for a text-only montage.")

    candidates: list[tuple[int, float]] = []
    for source_index, duration in usable:
        frames = analyses[source_index].get("frames", []) if analyses and source_index < len(analyses) else []
        for frame in frames:
            try:
                timestamp = float(frame["timestamp"])
            except (KeyError, TypeError, ValueError):
                continue
            if 0.25 < timestamp < duration - 1.0:
                candidates.append((source_index, timestamp))

    # If FFmpeg found no scene changes, retain a transparent deterministic fallback.
    if not candidates:
        for source_index, duration in usable:
            for index in range(1, 25):
                candidates.append((source_index, duration * index / 25))
    candidates.sort(key=lambda item: (item[0], item[1]))

    shot_count = max(5, min(24, round(target_seconds / 2.5)))
    # Crossfades shorten the assembled timeline; include their overlap in source footage.
    source_time_needed = target_seconds + 0.28 * (shot_count - 1)
    pattern = [1.9, 2.5, 2.1, 2.9, 2.2, 2.6]
    weights = [pattern[index % len(pattern)] for index in range(shot_count)]
    scale = source_time_needed / sum(weights)
    shot_lengths = [weight * scale for weight in weights]
    if max(shot_lengths) > 4.0 or min(shot_lengths) < 1.25:
        shot_lengths = [source_time_needed / shot_count] * shot_count

    edits = []
    for rank in range(1, output_count + 1):
        shots = []
        used: set[tuple[int, int]] = set()
        for index, shot_length in enumerate(shot_lengths):
            candidate_index = (index * len(candidates) // shot_count + (rank - 1) * max(1, len(candidates) // (output_count * shot_count))) % len(candidates)
            source_index, timestamp = candidates[candidate_index]
            duration = float(sources[source_index].get("duration_seconds") or 0)
            start = min(max(0.0, timestamp + 0.06), max(0.0, duration - shot_length))
            end = min(duration, start + shot_length)
            key = (source_index, round(start / 1.5))
            if key in used:
                for offset in range(1, len(candidates)):
                    alt_source, alt_timestamp = candidates[(candidate_index + offset) % len(candidates)]
                    alt_duration = float(sources[alt_source].get("duration_seconds") or 0)
                    alt_start = min(max(0.0, alt_timestamp + 0.06), max(0.0, alt_duration - shot_length))
                    alt_key = (alt_source, round(alt_start / 1.5))
                    if alt_key not in used:
                        source_index, duration, start = alt_source, alt_duration, alt_start
                        end, key = min(alt_duration, alt_start + shot_length), alt_key
                        break
            if end - start >= 1.25 and key not in used:
                used.add(key)
                shots.append(
                    {
                        "source_index": source_index,
                        "start_seconds": round(start, 3),
                        "end_seconds": round(end, 3),
                        "reason": (
                            "Selected near an FFmpeg-detected scene change; the installed text-only "
                            "model did not identify anime characters or story events."
                        ),
                    }
                )
        if len(shots) < 3:
            raise ValueError("Not enough distinct scene changes were found for a varied montage.")
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
