"""Lightweight campaign-aware visual sampling using a vision-capable LLM."""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path
from typing import Any

from clipyyy.media import ffmpeg_bin, run_ffmpeg

logger = logging.getLogger(__name__)


def supports_visual_input(llm) -> bool:
    """Return whether the configured model is known to accept image inputs."""
    if not hasattr(llm, "complete_json_with_images"):
        return False
    provider = getattr(llm, "provider", None)
    if provider is not None and getattr(provider, "local", False):
        model = str(getattr(llm, "model", "")).lower()
        vision_tags = ("qwen2.5vl", "qwen3-vl", "llava", "moondream", "minicpm-v", "gemma3")
        return any(tag in model for tag in vision_tags)
    return True


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
        run_ffmpeg(
            [
                "-ss",
                f"{timestamp:.3f}",
                "-i",
                str(video_path),
                "-frames:v",
                "1",
                "-vf",
                "scale=512:-2",
                "-q:v",
                "7",
                str(output),
            ]
        )
        if output.exists() and output.stat().st_size:
            samples.append((timestamp, str(output)))
    return samples


def detect_scene_changes(video_path: Path, duration: float, limit: int = 48) -> list[float]:
    """Return timestamps of visual cuts detected by FFmpeg's scene-change filter."""
    if duration <= 2:
        return []
    try:
        result = subprocess.run(
            [
                ffmpeg_bin(), "-hide_banner", "-loglevel", "info", "-i", str(video_path),
                "-vf", "fps=2,select='gt(scene,0.20)',showinfo", "-an", "-f", "null", "-",
            ],
            capture_output=True, text=True, timeout=180, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        logger.exception("FFmpeg scene detection failed for %s", video_path)
        return []
    timestamps = []
    for match in re.finditer(r"pts_time:([0-9]+(?:\.[0-9]+)?)", result.stderr or ""):
        timestamp = float(match.group(1))
        if 0.25 < timestamp < duration - 1.0:
            timestamps.append(timestamp)
    timestamps = sorted(set(round(value, 3) for value in timestamps))
    if len(timestamps) > limit:
        stride = (len(timestamps) - 1) / (limit - 1)
        timestamps = [timestamps[round(index * stride)] for index in range(limit)]
    return timestamps


def analyze_campaign_video(source: dict, work_dir: Path, llm, campaign_brief: str) -> dict:
    """Ask a vision model to describe sampled scenes in relation to the supplied campaign."""
    frames = sample_frames(Path(source["video_path"]), float(source.get("duration_seconds") or 0), work_dir)
    if not supports_visual_input(llm):
        logger.info("Text-only model; using FFmpeg scene boundaries without visual descriptions")
        duration = float(source.get("duration_seconds") or 0)
        scene_times = detect_scene_changes(Path(source["video_path"]), duration)
        timestamps = scene_times or [timestamp for timestamp, _ in frames]
        return {
            "frames": [
                {
                    "timestamp": timestamp,
                    "description": "Visual content unavailable: installed model is text-only.",
                    "mood": "unknown",
                    "subjects": "not analyzed",
                }
                for timestamp in timestamps
            ]
        }
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
        "Campaign brief:\n"
        + campaign_brief
        + "\n\nAnalyse these timestamped frames. Return one observation per frame, preserving each timestamp."
    )
    result = llm.complete_json_with_images(system, user, FRAME_SCHEMA, "campaign_visual_analysis", frames)
    valid = []
    for item in result.get("frames", []):
        try:
            timestamp = float(item["timestamp"])
        except (KeyError, TypeError, ValueError):
            continue
        valid.append(
            {
                "timestamp": timestamp,
                "description": str(item.get("description", ""))[:500],
                "mood": str(item.get("mood", ""))[:100],
                "subjects": str(item.get("subjects", ""))[:200],
            }
        )
    return {"frames": valid}


def analyze_reference_video(source: dict, work_dir: Path, llm) -> dict:
    """Describe the visible editing language of an accessible campaign reference video."""
    if not supports_visual_input(llm):
        return {"frames": []}
    frames = sample_frames(
        Path(source["video_path"]), float(source.get("duration_seconds") or 0), work_dir, limit=8
    )
    if not frames:
        return {"frames": []}
    system = (
        "You are a visual editing analyst studying a campaign reference video. "
        "Describe only visible evidence: "
        "shot scale, framing, composition, dominant colours, lighting, visible text or graphics, "
        "and recurring "
        "visual motifs. Do not claim to know the soundtrack, exact transitions, or motion from still frames. "
        "Do not recommend copying exact footage; extract reusable stylistic patterns only. "
        "Return JSON only."
    )
    user = (
        "Analyse these timestamped reference frames. Describe the visual style and recurring design language "
        "that could be recreated with different source footage. Preserve each supplied timestamp."
    )
    result = llm.complete_json_with_images(system, user, FRAME_SCHEMA, "campaign_reference_analysis", frames)
    valid = []
    for item in result.get("frames", []):
        try:
            timestamp = float(item["timestamp"])
        except (KeyError, TypeError, ValueError):
            continue
        valid.append(
            {
                "timestamp": timestamp,
                "description": str(item.get("description", ""))[:500],
                "mood": str(item.get("mood", ""))[:100],
                "subjects": str(item.get("subjects", ""))[:200],
            }
        )
    return {"frames": valid}
