"""Lightweight campaign-aware visual sampling using a vision-capable LLM."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from clipyyy.media import run_ffmpeg

logger = logging.getLogger(__name__)

FRAME_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "frames": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "timestamp": {"type": "number"},
                    "description": {"type": "string"},
                    "mood": {"type": "string"},
                    "subjects": {"type": "string"},
                },
                "required": ["timestamp", "description", "mood", "subjects"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["frames"],
    "additionalProperties": False,
}


def sample_frames(
    video_path: Path, duration: float, work_dir: Path, limit: int = 12
) -> list[tuple[float, str]]:
    """Extract evenly spaced, small JPEG frames without decoding the full video to disk."""
    if duration <= 0:
        return []
    count = min(limit, max(3, int(duration // 8) + 1))
    folder = work_dir / "campaign-frames"
    folder.mkdir(parents=True, exist_ok=True)
    samples: list[tuple[float, str]] = []
    for index in range(count):
        timestamp = min(max(0.5, duration * (index + 0.5) / count), max(0.5, duration - 0.2))
        output = folder / f"frame-{index:02d}.jpg"
        run_ffmpeg([
            "-ss", f"{timestamp:.3f}", "-i", str(video_path), "-frames:v", "1",
            "-vf", "scale=512:-2", "-q:v", "7", str(output),
        ])
        if output.exists() and output.stat().st_size:
            samples.append((timestamp, str(output)))
    return samples


def analyze_campaign_video(source: dict, work_dir: Path, llm, campaign_brief: str) -> dict:
    """Ask a vision model to describe sampled scenes in relation to the supplied campaign."""
    if not hasattr(llm, "complete_json_with_images"):
        logger.info("Selected model has no image-input support; skipping campaign visual analysis")
        return {"frames": []}
    frames = sample_frames(
        Path(source["video_path"]), float(source.get("duration_seconds") or 0), work_dir
    )
    if not frames:
        return {"frames": []}
    system = (
        "You are a professional short-form video editor analysing source footage for a campaign. "
        "Describe only what is visibly present. Do not guess character identities, plot, lyrics, or events. "
        "For every supplied frame return its exact supplied timestamp, concise visual description, emotional "
        "mood, and visible subjects. Keep descriptions useful for selecting emotionally and thematically "
        "relevant footage. Return JSON only."
    )
    user = (
        "Campaign brief:\n" + campaign_brief
        + "\n\nAnalyse these timestamped frames. Return one observation per frame, preserving each timestamp."
    )
    result = llm.complete_json_with_images(system, user, FRAME_SCHEMA, "campaign_visual_analysis", frames)
    valid = []
    for item in result.get("frames", []):
        try:
            timestamp = float(item["timestamp"])
        except (KeyError, TypeError, ValueError):
            continue
        valid.append({
            "timestamp": timestamp,
            "description": str(item.get("description", ""))[:500],
            "mood": str(item.get("mood", ""))[:100],
            "subjects": str(item.get("subjects", ""))[:200],
        })
    return {"frames": valid}
