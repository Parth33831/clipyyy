"""The clipping pipeline: a list of resumable stages.

Each stage writes ``<run>/work/<stage>.json``. If that file exists the stage is skipped on a
retry, so a failed run resumes where it stopped instead of downloading and transcribing again.
"""

from __future__ import annotations

import json
import logging
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from clipyyy import db
from clipyyy.config import get_setting, runs_dir

logger = logging.getLogger(__name__)

ASPECTS = {"9:16": 9 / 16, "4:5": 4 / 5, "1:1": 1.0}


class ClipOptions(BaseModel):
    clip_count: int = Field(3, ge=1, le=10, description="Maximum number of clips")
    min_seconds: float = Field(20, ge=5, le=170)
    max_seconds: float = Field(60, ge=10, le=180)
    aspect_ratio: Literal["9:16", "4:5", "1:1"] = "9:16"
    captions: bool = True
    source_has_subtitles: bool = False
    caption_style: Literal["bold", "highlight", "minimal"] = "bold"
    face_tracking: bool = True
    broll: bool = False
    language: str = Field("auto", description="Spoken language code, or auto")
    instructions: str = Field("", max_length=4000, description="Extra guidance for the AI")
    campaign_mode: bool = False
    campaign_brief: str = Field("", max_length=6000, description="Campaign requirements and creative brief")
    campaign_music_path: str | None = Field(None, description="Optional user-provided campaign music file")
    campaign_lyrics: str = Field(
        "", max_length=3000, description="Optional user-provided lyric or on-screen text lines"
    )
    model: str | None = Field(None, description="Override the default LLM model")

    @model_validator(mode="after")
    def _check_range(self) -> ClipOptions:
        if not self.campaign_mode and self.max_seconds < self.min_seconds + 5:
            raise ValueError("max_seconds must be at least 5 seconds more than min_seconds")
        return self


@dataclass(slots=True)
class Context:
    run_id: str
    source: str
    options: dict[str, Any]
    work_dir: Path
    out_dir: Path
    state: dict[str, Any]


def run_dir(run_id: str) -> Path:
    return runs_dir() / run_id


# ── stages ───────────────────────────────────────────────────────────────────


def stage_download(ctx: Context) -> dict:
    from clipyyy.source import fetch_source

    if ctx.options.get("campaign_mode"):
        sources = json.loads(ctx.source) if ctx.source.lstrip().startswith("[") else [ctx.source]
        from clipyyy.source import fetch_sources

        result = fetch_sources(sources, ctx.work_dir)
    else:
        result = fetch_source(ctx.source, ctx.work_dir)
    db.update_run(ctx.run_id, title=result["title"])
    return result


def stage_transcribe(ctx: Context) -> dict:
    if ctx.options.get("campaign_mode"):
        return {"language": "campaign", "sentences": [], "words": []}
    from clipyyy.transcribe import transcribe

    return transcribe(
        Path(ctx.state["download"]["video_path"]),
        ctx.work_dir,
        get_setting("whisper_model") or "base",
        ctx.options["language"],
    )


def stage_select(ctx: Context) -> dict:
    from clipyyy.llm import get_llm
    from clipyyy.selection import select_clips

    options = dict(ctx.options)
    defaults = get_setting("default_instructions").strip()
    if defaults:
        options["instructions"] = f"{defaults}\n{options['instructions']}".strip()
    llm = get_llm(options.get("model"))
    source = dict(ctx.state["download"])
    if options.get("campaign_mode"):
        if not options.get("campaign_brief", "").strip():
            raise ValueError("Add the campaign rules before starting a campaign edit.")
        if getattr(getattr(llm, "provider", None), "local", False):
            raise ValueError(
                "Campaign montage editing needs a vision-capable model. Select Gemini in Settings; "
                "local text-only Ollama cannot inspect video frames."
            )
        from clipyyy.campaign import build_montage_plan, parse_campaign_brief
        from clipyyy.vision import analyze_campaign_video

        plan = parse_campaign_brief(llm, options["campaign_brief"])
        sources = source.get("sources") or [source]
        analyses = []
        for index, item in enumerate(sources):
            analyses.append(
                analyze_campaign_video(
                    item,
                    ctx.work_dir / f"campaign-source-{index + 1:02d}",
                    llm,
                    options["campaign_brief"],
                )
            )
        count = min(10, plan.get("output_count") or options["clip_count"])
        target = plan.get("target_duration_seconds") or options["max_seconds"]
        edits = build_montage_plan(
            llm,
            options["campaign_brief"],
            plan,
            sources,
            analyses,
            count,
            target,
            options.get("instructions", ""),
        )
        db.update_run(ctx.run_id, title=plan.get("campaign_name") or source.get("title") or "Campaign edit")
        clips = []
        for edit in edits:
            duration = sum(shot["end_seconds"] - shot["start_seconds"] for shot in edit["shots"])
            clips.append(
                {
                    "rank": edit["rank"],
                    "title": edit["title"],
                    "post_title": edit["title"],
                    "caption": "",
                    "hashtags": [],
                    "rationale": "AI-selected campaign montage",
                    "score": None,
                    "transcript": "",
                    "start_seconds": 0.0,
                    "end_seconds": round(duration, 3),
                    "campaign_shots": edit["shots"],
                }
            )
        return {"campaign_plan": plan, "campaign_edits": edits, "clips": clips}
    return select_clips(llm, source, ctx.state["transcribe"], options)

def stage_plan(ctx: Context) -> dict:
    if ctx.options.get("campaign_mode"):
        return {
            "clips": [
                {
                    "rank": clip["rank"],
                    "start_seconds": 0.0,
                    "end_seconds": clip["end_seconds"],
                    "duration_seconds": clip["end_seconds"],
                    "windows": [],
                }
                for clip in ctx.state["select"]["clips"]
            ]
        }
    from clipyyy.timeline import plan_timeline

    return plan_timeline(ctx.state["select"], ctx.state["transcribe"], ctx.options["broll"])


def stage_broll(ctx: Context) -> dict:
    if ctx.options.get("campaign_mode"):
        return {"clips": []}
    from clipyyy.broll import fill_broll

    orientation = "square" if ctx.options["aspect_ratio"] == "1:1" else "portrait"
    return fill_broll(
        json.loads(json.dumps(ctx.state["plan"])), ctx.work_dir, get_setting("pexels_api_key"), orientation
    )


def stage_reframe(ctx: Context) -> dict:
    if ctx.options.get("campaign_mode"):
        return {"clips": []}
    from clipyyy.reframe import prepare_clips

    return prepare_clips(
        ctx.state["download"],
        ctx.state["plan"],
        ctx.work_dir,
        ASPECTS[ctx.options["aspect_ratio"]],
        ctx.options["face_tracking"],
        ctx.options["broll"],
    )


def stage_render(ctx: Context) -> dict:
    if ctx.options.get("campaign_mode"):
        from clipyyy.render import render_campaign_montages

        render_options = {
            **ctx.options,
            "campaign_plan": ctx.state["select"].get("campaign_plan"),
        }
        result = render_campaign_montages(
            ctx.state["download"], ctx.state["select"], ctx.work_dir, ctx.out_dir, render_options
        )
    else:
        from clipyyy.render import render_clips

        result = render_clips(
            ctx.state["download"],
            ctx.state["select"],
            ctx.state["broll"],
            ctx.state["reframe"],
            ctx.state["transcribe"],
            ctx.work_dir,
            ctx.out_dir,
            ctx.options,
        )
    renders = {r["rank"]: r for r in result["renders"]}
    db.replace_clips(
        ctx.run_id,
        [
            {
                "rank": clip["rank"],
                "start_seconds": clip["start_seconds"],
                "end_seconds": clip["end_seconds"],
                "title": clip["title"],
                "post_title": clip["post_title"],
                "caption": clip["caption"],
                "hashtags": clip["hashtags"],
                "rationale": clip["rationale"],
                "score": clip["score"],
                "transcript": clip["transcript"],
                "file_path": renders[clip["rank"]].get("file_path"),
                "width": renders[clip["rank"]].get("width"),
                "height": renders[clip["rank"]].get("height"),
                "duration_seconds": renders[clip["rank"]].get("duration_seconds"),
                "status": renders[clip["rank"]]["status"],
                "error": renders[clip["rank"]].get("error"),
            }
            for clip in ctx.state["select"]["clips"]
        ],
    )
    return result


STAGES: list[tuple[str, str, Callable[[Context], dict]]] = [
    ("download", "Download", stage_download),
    ("transcribe", "Transcribe", stage_transcribe),
    ("select", "Find clips", stage_select),
    ("plan", "Plan edits", stage_plan),
    ("broll", "B-roll", stage_broll),
    ("reframe", "Reframe", stage_reframe),
    ("render", "Render", stage_render),
]
STAGE_NAMES = [name for name, _, _ in STAGES]

# ── runner ───────────────────────────────────────────────────────────────────


def execute(run: dict[str, Any], on_stage: Callable[[str], None] | None = None) -> None:
    """Run (or resume) every stage for a claimed run. Marks the run completed or failed."""
    run_id = run["id"]
    ctx = Context(
        run_id=run_id,
        source=run["source"],
        options=ClipOptions(**run["options"]).model_dump(),
        work_dir=run_dir(run_id) / "work",
        out_dir=run_dir(run_id) / "clips",
        state={},
    )
    ctx.work_dir.mkdir(parents=True, exist_ok=True)
    for name, _, fn in STAGES:
        artifact = ctx.work_dir / f"{name}.json"
        if artifact.exists():
            ctx.state[name] = json.loads(artifact.read_text(encoding="utf-8"))
            db.set_stage(run_id, name, "done")
            continue
        db.update_run(run_id, current_stage=name)
        db.set_stage(run_id, name, "running")
        if on_stage:
            on_stage(name)
        try:
            result = fn(ctx)
        except Exception as exc:
            logger.exception("run %s failed in %s", run_id, name)
            db.set_stage(run_id, name, "failed", str(exc))
            db.update_run(run_id, status="failed", error=f"{name}: {exc}")
            return
        tmp = artifact.with_suffix(".tmp")
        tmp.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(artifact)
        ctx.state[name] = result
        db.set_stage(run_id, name, "done")
    db.update_run(run_id, status="completed", current_stage=None, error=None)


def retry(run_id: str, from_stage: str | None = None) -> None:
    """Queue a run again. With ``from_stage`` that stage and every later one are redone."""
    if from_stage:
        work = run_dir(run_id) / "work"
        for name in STAGE_NAMES[STAGE_NAMES.index(from_stage) :]:
            (work / f"{name}.json").unlink(missing_ok=True)
            db.set_stage(run_id, name, "pending")
    db.update_run(run_id, status="queued", error=None)


def delete(run_id: str) -> None:
    db.delete_run(run_id)
    shutil.rmtree(run_dir(run_id), ignore_errors=True)


def run_next() -> str | None:
    run = db.claim_next_run()
    if run is None:
        return None
    execute(run)
    return run["id"]
