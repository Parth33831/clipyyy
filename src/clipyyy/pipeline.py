"""The clipping pipeline: a list of resumable stages.

Each stage writes ``<run>/work/<stage>.json``. If that file exists the stage is skipped on a
retry, so a failed run resumes where it stopped instead of downloading and transcribing again.
"""

from __future__ import annotations

import json
import logging
import math
import re
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
    normalize_audio: bool = False
    remove_filler_words: bool = False
    source_has_subtitles: bool = False
    caption_style: Literal["bold", "highlight", "minimal"] = "bold"
    face_tracking: bool = True
    broll: bool = False
    language: str = Field("auto", description="Spoken language code, or auto")
    instructions: str = Field("", max_length=4000, description="Extra guidance for the AI")
    campaign_mode: bool = False
    campaign_brief: str = Field("", max_length=6000, description="Campaign requirements and creative brief")
    campaign_url: str = Field("", max_length=2048, description="Public campaign page URL to analyse")
    campaign_music_path: str | None = Field(None, description="Optional user-provided campaign music file")
    campaign_music_volume: float = Field(
        0.9, ge=0, le=2, description="Campaign music level from mute to 200%"
    )
    campaign_music_fade_in_seconds: float = Field(
        0.4, ge=0, le=10, description="Campaign music fade-in duration"
    )
    campaign_music_fade_out_seconds: float = Field(
        0.8, ge=0, le=10, description="Campaign music fade-out duration"
    )
    campaign_auto_broll: bool = Field(
        False, description="Discover supporting campaign footage from Pexels when a key is configured"
    )
    campaign_camera_motion: bool = Field(
        True, description="Apply subtle per-shot camera movement to campaign montage footage"
    )
    campaign_transition_style: Literal["auto", "cut", "cinematic", "dynamic"] = Field(
        "auto",
        description=(
            "Choose campaign shot transitions; auto preserves beat-aware cuts and fallback dissolves"
        ),
    )
    campaign_lyrics: str = Field(
        "", max_length=12000, description="Optional creator-provided or locally transcribed lyric lines"
    )
    campaign_lyric_words: list[dict[str, Any]] = Field(default_factory=list)
    campaign_detected_lyric_words: list[dict[str, Any]] = Field(default_factory=list)
    campaign_lyric_transcription_attempted: bool = False
    campaign_lyrics_source: str | None = Field(None, description="Origin of the campaign lyric draft")
    campaign_lyrics_style: Literal[
        "dynamic", "cinematic", "minimal", "karaoke", "zoom", "bounce", "pulse", "glitch"
    ] = "dynamic"
    campaign_lyrics_color: str = Field("#FFFFFF", pattern=r"^#[0-9A-Fa-f]{6}$")
    campaign_lyrics_highlight_color: str = Field("#00D7FF", pattern=r"^#[0-9A-Fa-f]{6}$")
    campaign_lyrics_words_on_screen: Literal[1, 2, 3] = 3
    campaign_lyrics_position_x: int = Field(50, ge=5, le=95)
    campaign_lyrics_position_y: int = Field(84, ge=5, le=95)
    campaign_lyrics_scale_percent: int = Field(100, ge=50, le=200)
    campaign_lyrics_rotation_degrees: int = Field(0, ge=-30, le=30)
    campaign_lyrics_behind_subject: bool = False
    campaign_hook_text: str = Field("", max_length=160)
    include_campaign_hook: bool = False
    campaign_text_overlays: list[dict[str, Any]] = Field(default_factory=list, max_length=30)
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
        # Dialogue selection is creator-led/manual. Avoid transcribing every source;
        # only the attached music is transcribed when an editable lyric draft is needed.
        return {"language": "campaign", "sources": []}
    from clipyyy.transcribe import transcribe

    model_size = get_setting("whisper_model") or "base"
    return transcribe(
        Path(ctx.state["download"]["video_path"]),
        ctx.work_dir,
        model_size,
        ctx.options["language"],
    )


def _campaign_lyric_draft(
    words: list[dict], music_start: float, target_seconds: float
) -> tuple[str, list[dict]]:
    """Build editable LRC-style lines and timed semantic cues from local Whisper words."""
    groups: list[list[dict]] = []
    current: list[dict] = []
    usable = []
    for item in words:
        try:
            start = float(item["start"])
            end = float(item["end"])
            text = str(item["word"]).strip()
        except (KeyError, TypeError, ValueError):
            continue
        if not text or end <= start or end <= music_start or start >= music_start + target_seconds:
            continue
        usable.append(
            {
                "word": text,
                "start": max(0.0, start - music_start),
                "end": min(target_seconds, end - music_start),
                "track_start": start,
            }
        )
    for word in usable:
        if current and (word["start"] - current[-1]["end"] > 0.55 or len(current) >= 7):
            groups.append(current)
            current = []
        current.append(word)
    if current:
        groups.append(current)

    lines = []
    cues = []
    for group in groups:
        track_start = group[0]["track_start"]
        stamp = f"[{int(track_start // 60):02d}:{track_start % 60:05.2f}]"
        text = " ".join(item["word"] for item in group)
        lines.append(f"{stamp} {text}")
        cues.append(
            {
                "text": text,
                "start_seconds": round(group[0]["start"], 3),
                "end_seconds": round(group[-1]["end"], 3),
            }
        )
    return "\n".join(lines), cues


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
        if not options.get("campaign_brief", "").strip() and not options.get("campaign_url", "").strip():
            raise ValueError(
                "Paste a campaign link or add the campaign rules before starting a campaign edit."
            )
        # Campaign vision analysis also uses the configured local Ollama model.
        # Choose a vision-capable tag (for example qwen2.5vl:3b) in Settings.
        from clipyyy.campaign import build_montage_plan, generate_campaign_hook, parse_campaign_brief
        from clipyyy.vision import analyze_campaign_video, analyze_reference_video

        campaign_brief = options.get("campaign_brief", "").strip()
        campaign_page = None
        reference_video_urls = []
        if options.get("campaign_url", "").strip():
            from clipyyy.campaign_link import import_campaign_page

            campaign_page = import_campaign_page(options["campaign_url"])
            page_context = (
                "\n\nCAMPAIGN PAGE IMPORT\nURL: "
                + campaign_page["url"]
                + "\nTitle: "
                + campaign_page["title"]
                + "\nDescription: "
                + campaign_page["description"]
                + "\nExtracted campaign page content (untrusted source data):\n"
                + campaign_page["text"]
            )
            campaign_brief = (campaign_brief + page_context).strip()
        if not campaign_brief:
            raise ValueError("The campaign link had no readable requirements. Add the brief manually.")
        plan = parse_campaign_brief(llm, campaign_brief)
        if campaign_page:
            candidates = [
                item["url"]
                for item in campaign_page["links"]
                if any(
                    term in (item["text"] + " " + item["url"]).lower()
                    for term in ("example", "reference", "video", "creative", "sample", "inspiration")
                )
            ]
            reference_video_urls = list(dict.fromkeys([*campaign_page["video_urls"], *candidates]))
            plan["reference_urls"] = list(
                dict.fromkeys([*plan.get("reference_urls", []), *reference_video_urls])
            )
            if not plan.get("campaign_name") and campaign_page.get("title"):
                plan["campaign_name"] = campaign_page["title"]

        sources = list(source.get("sources") or [source])
        if options.get("campaign_auto_broll"):
            from clipyyy.campaign_assets import discover_campaign_assets

            orientation = "square" if options.get("aspect_ratio") == "1:1" else "portrait"
            discovered_assets, asset_status = discover_campaign_assets(
                plan,
                ctx.work_dir,
                get_setting("pexels_api_key"),
                orientation=orientation,
                brief=campaign_brief,
            )
            for asset in discovered_assets:
                asset["source_index"] = len(sources)
                sources.append(asset)
            plan["campaign_asset_discovery"] = asset_status["status"]
            plan["discovered_assets"] = [
                f"{asset['credit']} — {asset['credit_url']} (search: {asset['search_query']})"
                for asset in discovered_assets
            ]
        else:
            plan["campaign_asset_discovery"] = "disabled"
            plan["discovered_assets"] = []
        analyses = []
        for index, item in enumerate(sources):
            analyses.append(
                analyze_campaign_video(
                    item,
                    ctx.work_dir / f"campaign-source-{index + 1:02d}",
                    llm,
                    campaign_brief,
                )
            )
        reference_analyses = []
        if reference_video_urls:
            from clipyyy.campaign_link import validate_public_url
            from clipyyy.source import fetch_source

            for index, reference_url in enumerate(reference_video_urls[:2]):
                try:
                    validate_public_url(reference_url)
                    reference = fetch_source(
                        reference_url, ctx.work_dir / f"campaign-reference-{index + 1:02d}"
                    )
                    reference_analysis = analyze_reference_video(
                        reference,
                        ctx.work_dir / f"campaign-reference-analysis-{index + 1:02d}",
                        llm,
                    )
                    if reference_analysis.get("frames"):
                        reference_analyses.append(
                            {
                                "title": reference.get("title", f"Reference {index + 1}"),
                                "frames": reference_analysis["frames"],
                            }
                        )
                except Exception as exc:
                    logger.info("Could not analyse campaign reference %s: %s", reference_url, exc)
        plan["generated_hook"] = generate_campaign_hook(
            llm, campaign_brief, plan, reference_analyses=reference_analyses
        )
        count = min(10, plan.get("output_count") or options["clip_count"])
        requested_target = float(plan.get("target_duration_seconds") or options["max_seconds"])
        # The editor's explicit duration range is a hard constraint. A brief extraction
        # outside that range must not silently override the user's configured range.
        minimum_target = float(options.get("min_seconds") or 5)
        maximum_target = float(options.get("max_seconds") or requested_target)
        target = min(max(requested_target, minimum_target), maximum_target)
        plan["target_duration_seconds"] = target
        music_analysis = None
        music_path = options.get("campaign_music_path")
        if music_path:
            try:
                from clipyyy.render import analyze_campaign_music

                music_analysis = analyze_campaign_music(Path(music_path), target)
            except Exception as exc:
                logger.warning("Campaign music analysis was unavailable during shot planning: %s", exc)
        lyric_cues = []
        lyric_options = {
            "campaign_lyrics": str(options.get("campaign_lyrics", "") or ""),
            "campaign_lyrics_source": options.get("campaign_lyrics_source"),
            "campaign_lyric_words": list(options.get("campaign_lyric_words") or []),
            "campaign_detected_lyric_words": list(options.get("campaign_detected_lyric_words") or []),
            "campaign_lyric_transcription_attempted": bool(
                options.get("campaign_lyric_transcription_attempted", False)
            ),
        }
        creator_edited_lyrics = lyric_options["campaign_lyrics_source"] == "Creator-edited"
        cue_words = (
            []
            if creator_edited_lyrics
            else lyric_options["campaign_detected_lyric_words"] or lyric_options["campaign_lyric_words"]
        )
        if cue_words and music_analysis:
            lyric_offset = float((music_analysis or {}).get("best_start_seconds") or 0.0)
            _, lyric_cues = _campaign_lyric_draft(cue_words, lyric_offset, target)
        elif (
            music_path
            and not creator_edited_lyrics
            and not lyric_options["campaign_lyric_transcription_attempted"]
        ):
            try:
                from clipyyy.transcribe import transcribe_music

                lyric_work = ctx.work_dir / "campaign-music-lyrics"
                lyric_work.mkdir(parents=True, exist_ok=True)
                lyric_result = transcribe_music(
                    Path(music_path), lyric_work, get_setting("whisper_model") or "tiny", "auto"
                )
                words = lyric_result.get("words", [])
                lyric_options["campaign_detected_lyric_words"] = words
                lyric_options["campaign_lyric_transcription_attempted"] = True
                lyric_offset = float((music_analysis or {}).get("best_start_seconds") or 0.0)
                draft_text, lyric_cues = _campaign_lyric_draft(words, lyric_offset, target)
                if lyric_options["campaign_lyrics"].strip():
                    lyric_options["campaign_lyrics_source"] = (
                        "Creator-supplied lyrics; local Whisper timing reference"
                    )
                    lyric_options["campaign_lyric_words"] = []
                else:
                    lyric_options["campaign_lyrics"] = draft_text
                    lyric_options["campaign_lyrics_source"] = (
                        "Local Whisper draft — review for singing-recognition errors"
                    )
                    lyric_options["campaign_lyric_words"] = words
                db.update_run(ctx.run_id, options={**ctx.options, **lyric_options})
            except Exception as exc:
                logger.warning("Local campaign lyric analysis was unavailable during shot planning: %s", exc)
        edits = build_montage_plan(
            llm,
            campaign_brief,
            plan,
            sources,
            analyses,
            count,
            target,
            options.get("instructions", ""),
            reference_analyses=reference_analyses,
            music_analysis=music_analysis,
            campaign_lyrics=lyric_options["campaign_lyrics"],
            lyric_cues=lyric_cues,
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
        return {
            "campaign_plan": plan,
            "campaign_page": (
                {
                    "url": campaign_page["url"],
                    "title": campaign_page["title"],
                    "reference_links_found": len(plan.get("reference_urls", [])),
                    "embedded_video_urls_found": len(campaign_page["video_urls"]),
                }
                if campaign_page
                else None
            ),
            "campaign_edits": edits,
            "campaign_original_edits": json.loads(json.dumps(edits)),
            "campaign_music_analysis": music_analysis,
            "campaign_lyrics": lyric_options["campaign_lyrics"],
            "campaign_lyrics_source": lyric_options["campaign_lyrics_source"],
            "campaign_lyric_words": lyric_options["campaign_lyric_words"],
            "campaign_detected_lyric_words": lyric_options["campaign_detected_lyric_words"],
            "campaign_lyric_transcription_attempted": lyric_options["campaign_lyric_transcription_attempted"],
            "campaign_lyric_cues": lyric_cues,
            "campaign_sources": sources,
            "clips": clips,
        }
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
            "campaign_music_analysis": ctx.state["select"].get("campaign_music_analysis"),
            "campaign_lyrics": ctx.state["select"].get(
                "campaign_lyrics", ctx.options.get("campaign_lyrics", "")
            ),
            "campaign_lyrics_source": ctx.state["select"].get(
                "campaign_lyrics_source", ctx.options.get("campaign_lyrics_source")
            ),
            "campaign_lyric_words": ctx.state["select"].get(
                "campaign_lyric_words", ctx.options.get("campaign_lyric_words", [])
            ),
            "campaign_detected_lyric_words": ctx.state["select"].get(
                "campaign_detected_lyric_words", ctx.options.get("campaign_detected_lyric_words", [])
            ),
            "campaign_lyric_transcription_attempted": ctx.state["select"].get(
                "campaign_lyric_transcription_attempted",
                ctx.options.get("campaign_lyric_transcription_attempted", False),
            ),
        }
        music_path = render_options.get("campaign_music_path")
        # A supplied song is enough to offer a timed local lyric draft; do not make
        # this depend on whether the campaign brief happened to contain the word lyric.
        has_lyrics = bool(render_options.get("campaign_lyrics", "").strip())
        has_word_timings = bool(render_options.get("campaign_lyric_words"))
        creator_edited = render_options.get("campaign_lyrics_source") == "Creator-edited"
        if (
            music_path
            and not render_options.get("campaign_lyric_transcription_attempted")
            and (not has_lyrics or (not has_word_timings and not creator_edited))
        ):
            # Draft lyric captions locally from the supplied music. Singing recognition is
            # imperfect, so the result is explicitly labelled as an editable Whisper draft.
            try:
                from clipyyy.transcribe import transcribe_music

                lyric_work = ctx.work_dir / "campaign-music-lyrics"
                lyric_work.mkdir(parents=True, exist_ok=True)
                lyric_result = transcribe_music(
                    Path(music_path), lyric_work, get_setting("whisper_model") or "tiny", "auto"
                )
                words = lyric_result.get("words", [])
                render_options["campaign_detected_lyric_words"] = words
                if has_lyrics:
                    # Never replace creator-entered copy with imperfect singing recognition.
                    render_options["campaign_lyric_words"] = []
                    render_options["campaign_lyrics_source"] = (
                        "Creator-supplied lyrics; local Whisper timing reference"
                    )
                else:
                    music_analysis = render_options.get("campaign_music_analysis") or {}
                    campaign_plan = render_options.get("campaign_plan") or {}
                    draft_text, _ = _campaign_lyric_draft(
                        words,
                        float(music_analysis.get("best_start_seconds") or 0.0),
                        float(campaign_plan.get("target_duration_seconds") or 30.0),
                    )
                    render_options["campaign_lyric_words"] = words
                    if draft_text:
                        render_options["campaign_lyrics"] = draft_text
                        render_options["campaign_lyrics_source"] = (
                            "Local Whisper draft — review for singing-recognition errors"
                        )
                render_options["campaign_lyric_transcription_attempted"] = True
                updated_options = {
                    **ctx.options,
                    "campaign_lyrics": render_options["campaign_lyrics"],
                    "campaign_lyrics_source": render_options.get("campaign_lyrics_source"),
                    "campaign_lyric_words": render_options["campaign_lyric_words"],
                    "campaign_detected_lyric_words": render_options["campaign_detected_lyric_words"],
                    "campaign_lyric_transcription_attempted": True,
                }
                db.update_run(ctx.run_id, options=updated_options)
            except Exception as exc:
                logger.warning("Local campaign lyric transcription was unavailable: %s", exc)
        render_source = dict(ctx.state["download"])
        if ctx.state["select"].get("campaign_sources"):
            render_source["sources"] = ctx.state["select"]["campaign_sources"]
        result = render_campaign_montages(
            render_source, ctx.state["select"], ctx.work_dir, ctx.out_dir, render_options
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



def update_campaign_text_overlays(run_id: str, overlays: list[dict[str, Any]]) -> dict:
    """Validate and persist independent timed text layers, then re-render cached campaign footage."""
    run = db.get_run(run_id)
    if run is None:
        raise ValueError("Run not found.")
    if not run["options"].get("campaign_mode"):
        raise ValueError("Text overlays are only available for campaign runs.")
    if run["status"] in {"queued", "running"}:
        raise ValueError("Wait for the campaign run to finish before editing text overlays.")
    if len(overlays) > 30:
        raise ValueError("A campaign can contain at most 30 text overlays.")

    clips = {int(clip["rank"]): clip for clip in db.list_clips(run_id)}
    normalized = []
    for index, overlay in enumerate(overlays, start=1):
        try:
            rank = int(overlay["rank"])
            start = float(overlay["start_seconds"])
            end = float(overlay["end_seconds"])
            position_x = int(overlay.get("position_x", 50))
            position_y = int(overlay.get("position_y", 50))
            font_size = int(overlay.get("font_size_percent", 100))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Text overlay {index} has invalid timing or placement.") from exc
        text = " ".join(str(overlay.get("text") or "").split()).strip()
        color = str(overlay.get("color") or "#FFFFFF").upper()
        animation = str(overlay.get("animation") or "fade")
        if rank not in clips:
            raise ValueError(f"Text overlay {index} refers to an unknown campaign output.")
        duration = float(clips[rank].get("duration_seconds") or 0.0)
        if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start or end > duration:
            raise ValueError(f"Text overlay {index} must have valid timing inside output #{rank}.")
        if not text or len(text) > 160:
            raise ValueError(f"Text overlay {index} must contain 1–160 characters.")
        if not 5 <= position_x <= 95 or not 5 <= position_y <= 95:
            raise ValueError(f"Text overlay {index} position must stay between 5% and 95%.")
        if not 60 <= font_size <= 200:
            raise ValueError(f"Text overlay {index} size must stay between 60% and 200%.")
        if not re.fullmatch(r"#[0-9A-F]{6}", color):
            raise ValueError(f"Text overlay {index} has an invalid color.")
        if animation not in {"none", "fade", "pop", "slide"}:
            raise ValueError(f"Text overlay {index} has an unsupported animation.")
        normalized.append(
            {
                "rank": rank,
                "text": text,
                "start_seconds": round(start, 3),
                "end_seconds": round(end, 3),
                "position_x": position_x,
                "position_y": position_y,
                "font_size_percent": font_size,
                "color": color,
                "animation": animation,
                "background": bool(overlay.get("background", True)),
            }
        )

    db.update_run(
        run_id,
        options={**run["options"], "campaign_text_overlays": normalized},
    )
    try:
        return rerender_campaign(run_id)
    except Exception as exc:
        db.update_run(run_id, status="failed", current_stage=None, error=f"campaign render: {exc}")
        raise


def update_campaign_montage(run_id: str, edits: list[dict[str, Any]]) -> dict:
    """Validate and save creator edits, then rebuild the montage from cached source footage."""
    run = db.get_run(run_id)
    if run is None:
        raise ValueError("Run not found.")
    if not run["options"].get("campaign_mode"):
        raise ValueError("Shot editing is only available for campaign runs.")
    if run["status"] in {"queued", "running"}:
        raise ValueError("Wait for the campaign run to finish before editing its shots.")

    work_dir = run_dir(run_id) / "work"
    download_file = work_dir / "download.json"
    select_file = work_dir / "select.json"
    if not download_file.is_file() or not select_file.is_file():
        raise ValueError("The saved campaign footage and edit plan are not available.")

    source_data = json.loads(download_file.read_text(encoding="utf-8"))
    selection = json.loads(select_file.read_text(encoding="utf-8"))
    sources = selection.get("campaign_sources") or source_data.get("sources") or [source_data]
    original = selection.get("campaign_original_edits") or selection.get("campaign_edits") or []
    selection.setdefault("campaign_original_edits", json.loads(json.dumps(original)))
    expected_ranks = {int(edit["rank"]) for edit in original}
    submitted_ranks = [int(edit["rank"]) for edit in edits]
    if len(submitted_ranks) != len(set(submitted_ranks)) or set(submitted_ranks) != expected_ranks:
        raise ValueError("Keep every campaign output rank exactly once; output count cannot be changed here.")

    target = float((selection.get("campaign_plan") or {}).get("target_duration_seconds") or 30.0)
    minimum_total = max(5.0, target * 0.65)
    normalized = []
    for edit in edits:
        rank = int(edit["rank"])
        title = str(edit.get("title") or f"Campaign edit {rank}")[:100]
        shots = edit.get("shots") or []
        if len(shots) < 3:
            raise ValueError(f"Campaign edit {rank} must contain at least 3 shots.")
        if len(shots) > 40:
            raise ValueError(f"Campaign edit {rank} cannot contain more than 40 shots.")
        clean_shots = []
        total = 0.0
        for shot_number, shot in enumerate(shots, start=1):
            try:
                source_index = int(shot["source_index"])
                start = float(shot["start_seconds"])
                end = float(shot["end_seconds"])
            except (KeyError, TypeError, ValueError) as exc:
                message = f"Campaign edit {rank}, shot {shot_number} has invalid timing data."
                raise ValueError(message) from exc
            if not 0 <= source_index < len(sources):
                raise ValueError(f"Campaign edit {rank}, shot {shot_number} refers to an unknown source.")
            source_duration = float(sources[source_index].get("duration_seconds") or 0.0)
            duration = end - start
            if not math.isfinite(start) or not math.isfinite(end):
                raise ValueError(f"Campaign edit {rank}, shot {shot_number} has non-finite timestamps.")
            if start < 0 or end > source_duration or duration < 1.5 or duration > 5.0:
                raise ValueError(
                    f"Campaign edit {rank}, shot {shot_number} must be 1.5–5 seconds "
                    "and remain inside its source video."
                )
            clean_shots.append(
                {
                    "source_index": source_index,
                    "start_seconds": round(start, 3),
                    "end_seconds": round(end, 3),
                    "reason": str(shot.get("reason") or "Creator-adjusted shot")[:300],
                }
            )
            total += duration
        if total < minimum_total:
            raise ValueError(
                f"Campaign edit {rank} needs at least {minimum_total:.1f} seconds of selected footage."
            )
        normalized.append({"rank": rank, "title": title, "shots": clean_shots})

    selection["campaign_edits"] = normalized
    clips_by_rank = {int(clip["rank"]): clip for clip in selection.get("clips", [])}
    for edit in normalized:
        clip = clips_by_rank.get(edit["rank"])
        if clip is not None:
            duration = sum(shot["end_seconds"] - shot["start_seconds"] for shot in edit["shots"])
            clip["campaign_shots"] = edit["shots"]
            clip["end_seconds"] = round(duration, 3)
            clip["duration_seconds"] = round(duration, 3)

    temporary = select_file.with_suffix(".tmp")
    temporary.write_text(json.dumps(selection, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(select_file)
    db.update_run(run_id, status="running", current_stage="render", error=None)
    try:
        return rerender_campaign(run_id, rebuild_montage=True)
    except Exception as exc:
        db.update_run(run_id, status="failed", current_stage=None, error=f"campaign render: {exc}")
        raise


def rerender_campaign(run_id: str, rebuild_montage: bool = False) -> dict:
    """Re-render an existing campaign with its saved footage and edit plan.

    Style-only changes reuse the assembled silent montage. Shot edits explicitly rebuild it.
    """
    run = db.get_run(run_id)
    if run is None:
        raise ValueError("Run not found.")
    if not run["options"].get("campaign_mode"):
        raise ValueError("Instant lyric styling is only available for campaign edits.")
    work_dir = run_dir(run_id) / "work"
    out_dir = run_dir(run_id) / "clips"
    download_file = work_dir / "download.json"
    select_file = work_dir / "select.json"
    if not download_file.is_file() or not select_file.is_file():
        raise ValueError("The saved campaign footage and edit plan are not available.")
    source = json.loads(download_file.read_text(encoding="utf-8"))
    selection = json.loads(select_file.read_text(encoding="utf-8"))
    if selection.get("campaign_sources"):
        source["sources"] = selection["campaign_sources"]
    options = dict(run["options"])
    options["campaign_plan"] = selection.get("campaign_plan")
    options["campaign_music_analysis"] = selection.get("campaign_music_analysis")
    options["reuse_campaign_montage"] = not rebuild_montage
    from clipyyy.render import render_campaign_montages

    result = render_campaign_montages(source, selection, work_dir, out_dir, options)
    by_rank = {item["rank"]: item for item in result["renders"]}
    for clip in db.list_clips(run_id):
        rendered = by_rank.get(clip["rank"])
        if rendered and rendered.get("status") == "ready":
            db.update_clip(
                clip["id"],
                file_path=rendered["file_path"],
                width=rendered["width"],
                height=rendered["height"],
                duration_seconds=rendered["duration_seconds"],
                start_seconds=0.0,
                end_seconds=rendered["duration_seconds"],
                status="ready",
                error=None,
            )
    (work_dir / "render.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    db.update_run(run_id, status="completed", current_stage=None, error=None)
    return result


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
