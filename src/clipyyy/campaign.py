"""Universal campaign brief understanding and validation.

The model extracts requirements without assigning fixed niche-specific presets. Unknown
requirements remain null/empty; the original brief is always preserved separately.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CampaignPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    campaign_name: str | None = None
    platform: list[str] = Field(default_factory=list)
    content_type: str | None = None
    subject_or_theme: str | None = None
    mood: list[str] = Field(default_factory=list)
    language: str | None = None
    output_count: int | None = Field(default=None, ge=1, le=50)
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
    result = llm.complete_json(
        PLAN_SYSTEM,
        "Extract the requirements from this campaign brief. Do not add assumptions.\n\n" + text,
        PLAN_SCHEMA,
        "campaign_requirements",
    )
    return CampaignPlan.model_validate(result).model_dump()


def local_fallback_plan(brief: str) -> dict[str, Any]:
    """A transparent fallback for local text-only models; makes no inferred claims."""
    return {
        **CampaignPlan().model_dump(),
        "unresolved_questions": [
            "Structured AI interpretation was skipped for the local text-only model. The full brief will still guide clip selection."
        ],
    }


def format_campaign_plan(plan: dict[str, Any]) -> str:
    """Compact, explicit plan for downstream creative selection."""
    labels = {
        "campaign_name": "Campaign",
        "platform": "Platform",
        "content_type": "Content type",
        "subject_or_theme": "Subject/theme",
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
        "rights_or_permissions_to_confirm": "Rights/permissions to confirm",
        "unresolved_questions": "Unresolved",
    }
    lines = []
    for key, label in labels.items():
        value = plan.get(key)
        if value is not None and value != []:
            lines.append(f"- {label}: {', '.join(map(str, value)) if isinstance(value, list) else value}")
    return "\n".join(lines) if lines else "- No structured requirements extracted; follow the original brief exactly."
