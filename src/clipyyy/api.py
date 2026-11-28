"""HTTP API and web UI."""

from __future__ import annotations

import json
import math
import mimetypes
import os
import subprocess
import zipfile
from array import array
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator

from clipyyy import __version__, campaign, db, pipeline
from clipyyy.config import PACKAGE_DIR, SETTINGS, get_setting, home, mask, uploads_dir
from clipyyy.doctor import checks
from clipyyy.llm import get_llm
from clipyyy.publish import BufferClient, PublishError, PublishMode, publish_clip
from clipyyy.worker import Worker

WEB_DIR = PACKAGE_DIR / "web"

DEFAULT_VIDEO_UPLOAD_LIMIT_BYTES = 50 * 1024**3
DEFAULT_CAMPAIGN_MUSIC_UPLOAD_LIMIT_BYTES = 2 * 1024**3


def _configured_upload_limit(name: str, default: int) -> int:
    """Read a positive byte limit from the environment, falling back safely."""
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


MAX_VIDEO_UPLOAD_BYTES = _configured_upload_limit(
    "CLIPYYY_MAX_VIDEO_UPLOAD_BYTES", DEFAULT_VIDEO_UPLOAD_LIMIT_BYTES
)
MAX_CAMPAIGN_MUSIC_UPLOAD_BYTES = _configured_upload_limit(
    "CLIPYYY_MAX_CAMPAIGN_MUSIC_UPLOAD_BYTES", DEFAULT_CAMPAIGN_MUSIC_UPLOAD_LIMIT_BYTES
)


def _save_limited_upload(file: UploadFile, target: Path, max_bytes: int, label: str) -> int:
    """Stream an upload to disk with a hard byte limit and remove partial files on failure."""
    target.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    try:
        with target.open("wb") as output:
            while chunk := file.file.read(1024 * 1024):
                total += len(chunk)
                if total > max_bytes:
                    raise HTTPException(
                        413,
                        f"{label} exceeds the configured upload limit ({max_bytes} bytes).",
                    )
                output.write(chunk)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return total


class CreateRuns(BaseModel):
    sources: list[str] = Field(..., min_length=1, max_length=50)
    options: pipeline.ClipOptions = pipeline.ClipOptions()


class RetryRun(BaseModel):
    from_stage: str | None = None


class CampaignAudioUpdate(BaseModel):
    music_volume: float = Field(0.9, ge=0, le=2)
    source_audio_volume: float = Field(1.0, ge=0, le=2)
    duck_music: bool = False
    music_start_seconds: float | None = Field(None, ge=0, le=7200)
    fade_in_seconds: float = Field(0.4, ge=0, le=10)
    fade_out_seconds: float = Field(0.8, ge=0, le=10)


class CampaignLyricPhraseEdit(BaseModel):
    phrase_index: int = Field(..., ge=0, le=199)
    start_seconds: float | None = Field(None, ge=0)
    end_seconds: float | None = Field(None, gt=0)
    position_x: int | None = Field(None, ge=5, le=95)
    position_y: int | None = Field(None, ge=5, le=95)
    scale_percent: int | None = Field(None, ge=50, le=200)
    rotation_degrees: int | None = Field(None, ge=-30, le=30)
    animation_style: Literal["dynamic", "cinematic", "minimal", "karaoke"] | None = None

    @model_validator(mode="after")
    def _valid_timing(self) -> CampaignLyricPhraseEdit:
        if (
            self.start_seconds is not None
            and self.end_seconds is not None
            and self.end_seconds <= self.start_seconds
        ):
            raise ValueError("Phrase end_seconds must be after start_seconds")
        return self


class CampaignLyricWordEdit(BaseModel):
    word_index: int = Field(..., ge=0, le=1999)
    word: str | None = Field(None, min_length=1, max_length=80)
    start: float | None = Field(None, ge=0)
    end: float | None = Field(None, gt=0)

    @model_validator(mode="after")
    def _valid_timing(self) -> CampaignLyricWordEdit:
        if self.start is not None and self.end is not None and self.end <= self.start:
            raise ValueError("Word end must be after word start")
        return self


class CampaignLyricWord(BaseModel):
    word: str = Field(..., min_length=1, max_length=80)
    start: float = Field(..., ge=0)
    end: float = Field(..., gt=0)

    @model_validator(mode="after")
    def _valid_timing(self) -> CampaignLyricWord:
        if self.end <= self.start:
            raise ValueError("Word end must be after word start")
        if not self.word.strip():
            raise ValueError("Lyric words cannot be blank")
        return self


class CampaignLyricsUpdate(BaseModel):
    lyrics: str = Field("", max_length=12000)
    lyrics_style: Literal[
        "dynamic", "cinematic", "minimal", "karaoke", "zoom", "bounce", "pulse", "glitch"
    ] = "dynamic"
    lyrics_color: str = Field("#FFFFFF", pattern=r"^#[0-9A-Fa-f]{6}$")
    highlight_color: str = Field("#00D7FF", pattern=r"^#[0-9A-Fa-f]{6}$")
    words_on_screen: Literal[1, 2, 3] = 3
    position_x: int = Field(50, ge=5, le=95)
    position_y: int = Field(84, ge=5, le=95)
    scale_percent: int = Field(100, ge=50, le=200)
    rotation_degrees: int = Field(0, ge=-30, le=30)
    lyrics_behind_subject: bool = False
    hook_text: str = Field("", max_length=160)
    include_hook: bool = False
    phrase_edits: list[CampaignLyricPhraseEdit] = Field(default_factory=list, max_length=200)
    word_edits: list[CampaignLyricWordEdit] = Field(default_factory=list, max_length=2000)
    replace_words: list[CampaignLyricWord] | None = Field(None, max_length=2000)


class CampaignTextOverlay(BaseModel):
    rank: int = Field(..., ge=1, le=10)
    text: str = Field(..., min_length=1, max_length=160)
    start_seconds: float = Field(..., ge=0)
    end_seconds: float = Field(..., gt=0)
    position_x: int = Field(50, ge=5, le=95)
    position_y: int = Field(50, ge=5, le=95)
    font_size_percent: int = Field(100, ge=60, le=200)
    rotation_degrees: int = Field(0, ge=-30, le=30)
    font_family: Literal["Arial", "Georgia", "Impact", "Trebuchet MS", "Verdana"] = "Arial"
    font_weight: Literal["regular", "bold"] = "bold"
    text_effect: Literal["none", "shadow", "outline"] = "shadow"
    color: str = Field("#FFFFFF", pattern=r"^#[0-9A-Fa-f]{6}$")
    animation: Literal["none", "fade", "pop", "slide"] = "fade"
    background: bool = True


class CampaignTextOverlaysUpdate(BaseModel):
    overlays: list[CampaignTextOverlay] = Field(default_factory=list, max_length=30)


class CampaignShotEdit(BaseModel):
    source_index: int = Field(..., ge=0)
    start_seconds: float = Field(..., ge=0)
    end_seconds: float = Field(..., gt=0)
    reason: str = Field("", max_length=300)


class CampaignEditUpdate(BaseModel):
    rank: int = Field(..., ge=1)
    title: str = Field(..., min_length=1, max_length=100)
    shots: list[CampaignShotEdit] = Field(..., min_length=3, max_length=40)


class CampaignMontageUpdate(BaseModel):
    edits: list[CampaignEditUpdate] = Field(..., min_length=1, max_length=10)


class CampaignAiEditRequest(BaseModel):
    current_edit: CampaignEditUpdate
    creative_direction: str = Field("", max_length=1000)


class CampaignLyricsAlignRequest(BaseModel):
    lyrics: str = Field(..., min_length=1, max_length=12000)


class UpdateSettings(BaseModel):
    values: dict[str, str | None]


class PublishRequest(BaseModel):
    channel_ids: list[str] = Field(..., min_length=1)
    mode: PublishMode = "queue"
    scheduled_at: datetime | None = None
    text: str | None = None
    title: str | None = None


def create_app(start_worker: bool = True) -> FastAPI:
    worker = Worker() if start_worker else None

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if worker:
            worker.start()
        yield
        if worker:
            worker.stop()

    app = FastAPI(title="clipyyy", version=__version__, lifespan=lifespan)

    # ── health & settings ────────────────────────────────────────────────────

    @app.get("/api/health")
    def health() -> dict:
        return {
            "version": __version__,
            "checks": checks(),
            "queue": db.queue_counts(),
            "worker": bool(worker),
        }

    @app.get("/api/settings")
    def get_settings() -> list[dict]:
        result = []
        for key, spec in SETTINGS.items():
            stored = db.get_setting(key)
            value = get_setting(key)
            source = "app" if stored else "env" if os.environ.get(spec.env) else "default"
            result.append(
                {
                    "key": key,
                    "value": mask(value) if spec.secret else value,
                    "is_set": bool(value),
                    "secret": spec.secret,
                    "source": source,
                    "env": spec.env,
                    "description": spec.description,
                }
            )
        return result

    @app.put("/api/settings")
    def put_settings(body: UpdateSettings) -> list[dict]:
        for key, value in body.values.items():
            if key not in SETTINGS:
                raise HTTPException(400, f"Unknown setting: {key}")
            if SETTINGS[key].secret and value and "••••" in value:
                continue  # unchanged masked value sent back by the UI
            db.set_setting(key, value.strip() if value else None)
        return get_settings()

    @app.get("/api/models")
    def models() -> list[dict]:
        from clipyyy.llm import list_models

        try:
            return list_models()
        except Exception as exc:
            raise HTTPException(502, f"Could not load models: {exc}") from exc

    # ── runs ─────────────────────────────────────────────────────────────────

    @app.post("/api/uploads")
    def upload(file: UploadFile) -> dict:
        name = Path((file.filename or "upload.mp4").replace("\\\\", "/")).name
        target = uploads_dir() / f"{db.new_id()}-{name}"
        size_bytes = _save_limited_upload(file, target, MAX_VIDEO_UPLOAD_BYTES, "Video upload")
        return {"source": str(target), "name": name, "size_bytes": size_bytes}

    @app.put("/api/runs/{run_id}/campaign-lyrics")
    def update_campaign_lyrics(run_id: str, body: CampaignLyricsUpdate) -> dict:
        run = _run_or_404(run_id)
        if not run["options"].get("campaign_mode"):
            raise HTTPException(400, "Lyrics can only be edited on campaign runs.")
        if run["status"] in {"queued", "running"}:
            raise HTTPException(409, "Wait for the campaign run to finish before editing lyrics.")
        lyrics_unchanged = body.lyrics == run["options"].get("campaign_lyrics", "")
        existing_words = list(run["options"].get("campaign_lyric_words", [])) if lyrics_unchanged else []
        if body.replace_words is not None:
            existing_words = [item.model_dump() for item in body.replace_words]
        for edit in body.word_edits:
            if edit.word_index >= len(existing_words):
                raise HTTPException(422, f"Lyrics word {edit.word_index + 1} no longer exists.")
            word = dict(existing_words[edit.word_index])
            if edit.word is not None:
                word["word"] = edit.word.strip()
            if edit.start is not None:
                word["start"] = edit.start
            if edit.end is not None:
                word["end"] = edit.end
            if float(word.get("end", 0)) <= float(word.get("start", 0)):
                raise HTTPException(
                    422,
                    f"Timing for word {edit.word_index + 1} must have a positive duration.",
                )
            existing_words[edit.word_index] = word
        options = {
            **run["options"],
            "campaign_lyrics": body.lyrics,
            "campaign_lyrics_source": (
                run["options"].get("campaign_lyrics_source", "Local Whisper draft")
                if lyrics_unchanged
                else "Creator-edited"
            ),
            # Preserve Whisper's word timings when only style or hook settings change.
            "campaign_lyric_words": existing_words,
            "campaign_lyrics_style": body.lyrics_style,
            "campaign_lyrics_color": body.lyrics_color.upper(),
            "campaign_lyrics_highlight_color": body.highlight_color.upper(),
            "campaign_lyrics_words_on_screen": body.words_on_screen,
            "campaign_lyrics_position_x": body.position_x,
            "campaign_lyrics_position_y": body.position_y,
            "campaign_lyrics_scale_percent": body.scale_percent,
            "campaign_lyrics_rotation_degrees": body.rotation_degrees,
            "campaign_lyric_phrase_edits": [item.model_dump(exclude_none=True) for item in body.phrase_edits],
            "campaign_lyrics_behind_subject": body.lyrics_behind_subject,
            "campaign_hook_text": body.hook_text.strip(),
            "include_campaign_hook": body.include_hook,
        }
        db.update_run(run_id, options=options)
        try:
            result = pipeline.rerender_campaign(run_id)
        except Exception as exc:
            raise HTTPException(500, f"Could not apply the lyric changes: {exc}") from exc
        return {
            "saved": True,
            "rendered": True,
            "characters": len(body.lyrics),
            "outputs": len(result.get("renders", [])),
        }

    @app.post("/api/runs/{run_id}/campaign-lyrics-resync")
    def propose_campaign_lyrics_resync(run_id: str) -> dict:
        """Transcribe attached campaign music and return a review-only lyric proposal."""
        run = _run_or_404(run_id)
        if not run["options"].get("campaign_mode"):
            raise HTTPException(400, "Lyric re-sync is only available for campaign runs.")
        if run["status"] in {"queued", "running"}:
            raise HTTPException(409, "Wait for the campaign run to finish before re-syncing lyrics.")
        music_path = run["options"].get("campaign_music_path")
        if not music_path or not Path(str(music_path)).is_file():
            raise HTTPException(404, "Attach an available music track before re-syncing lyrics.")
        try:
            from clipyyy.transcribe import transcribe_music

            work_dir = pipeline.run_dir(run_id) / "work" / "campaign-lyrics-resync"
            result = transcribe_music(
                Path(str(music_path)), work_dir, get_setting("whisper_model") or "tiny", "auto"
            )
            words = result.get("words") or []
            if not words:
                raise HTTPException(422, "No lyric words could be detected in this soundtrack.")
            lyric_offset = float(run["options"].get("campaign_music_start_seconds") or 0)
            selection_path = pipeline.run_dir(run_id) / "work" / "select.json"
            if selection_path.is_file():
                selection = json.loads(selection_path.read_text(encoding="utf-8"))
                analysis = selection.get("campaign_music_analysis") or {}
                lyric_offset = float(analysis.get("best_start_seconds") or lyric_offset)
            draft, _ = pipeline._campaign_lyric_draft(words, lyric_offset, 180.0)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(503, f"Could not re-sync soundtrack lyrics: {exc}") from exc
        return {
            "lyrics": draft,
            "words": words,
            "language": result.get("language"),
            "word_count": len(words),
            "saved": False,
            "rendered": False,
        }

    @app.post("/api/runs/{run_id}/campaign-lyrics-align")
    def align_campaign_lyrics(run_id: str, body: CampaignLyricsAlignRequest) -> dict:
        """Align creator-supplied words to attached soundtrack timestamps without replacing text."""
        run = _run_or_404(run_id)
        if not run["options"].get("campaign_mode"):
            raise HTTPException(400, "Lyric alignment is only available for campaign runs.")
        if run["status"] in {"queued", "running"}:
            raise HTTPException(409, "Wait for the campaign run to finish before aligning lyrics.")
        music_path = run["options"].get("campaign_music_path")
        if not music_path or not Path(str(music_path)).is_file():
            raise HTTPException(404, "Attach an available music track before aligning lyrics.")
        try:
            from clipyyy.transcribe import align_lyric_text_to_words, transcribe_music

            work_dir = pipeline.run_dir(run_id) / "work" / "campaign-lyrics-align"
            result = transcribe_music(
                Path(str(music_path)), work_dir, get_setting("whisper_model") or "tiny", "auto"
            )
            alignment = align_lyric_text_to_words(body.lyrics, result.get("words") or [])
            if not alignment["matched_count"]:
                raise HTTPException(
                    422,
                    (
                        "None of those lyric words could be matched to the soundtrack. "
                        "Check the lyrics or try a clearer vocal track."
                    ),
                )
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(503, f"Could not align your lyrics to the soundtrack: {exc}") from exc
        return {
            "lyrics": body.lyrics,
            **alignment,
            "language": result.get("language"),
            "mode": "alignment",
            "saved": False,
            "rendered": False,
        }

    @app.put("/api/runs/{run_id}/campaign-text-overlays")
    def update_campaign_text_overlays(run_id: str, body: CampaignTextOverlaysUpdate) -> dict:
        run = _run_or_404(run_id)
        if not run["options"].get("campaign_mode"):
            raise HTTPException(400, "Text overlays are only available for campaign runs.")
        if run["status"] in {"queued", "running"}:
            raise HTTPException(409, "Wait for the campaign run to finish before editing text overlays.")
        try:
            result = pipeline.update_campaign_text_overlays(
                run_id, [overlay.model_dump() for overlay in body.overlays]
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(500, f"Could not apply campaign text overlays: {exc}") from exc
        return {
            "saved": True,
            "rendered": True,
            "overlays": len(body.overlays),
            "outputs": len(result.get("renders", [])),
        }

    @app.put("/api/runs/{run_id}/campaign-audio")
    def update_campaign_audio(run_id: str, body: CampaignAudioUpdate) -> dict:
        run = _run_or_404(run_id)
        if not run["options"].get("campaign_mode"):
            raise HTTPException(400, "Music settings are only available for campaign runs.")
        if run["status"] in {"queued", "running"}:
            raise HTTPException(409, "Wait for the campaign run to finish before changing its music mix.")
        options = {
            **run["options"],
            "campaign_music_volume": body.music_volume,
            "campaign_source_audio_volume": body.source_audio_volume,
            "campaign_music_ducking": body.duck_music,
            "campaign_music_start_seconds": body.music_start_seconds,
            "campaign_music_fade_in_seconds": body.fade_in_seconds,
            "campaign_music_fade_out_seconds": body.fade_out_seconds,
        }
        db.update_run(run_id, options=options)
        try:
            result = pipeline.rerender_campaign(run_id)
        except Exception as exc:
            raise HTTPException(500, f"Could not apply the campaign music mix: {exc}") from exc
        return {"saved": True, "rendered": True, "outputs": len(result.get("renders", []))}

    @app.put("/api/runs/{run_id}/campaign-montage")
    def update_campaign_montage(run_id: str, body: CampaignMontageUpdate) -> dict:
        run = _run_or_404(run_id)
        if not run["options"].get("campaign_mode"):
            raise HTTPException(400, "Shot editing is only available for campaign runs.")
        if run["status"] in {"queued", "running"}:
            raise HTTPException(409, "Wait for the campaign run to finish before editing its shots.")
        try:
            result = pipeline.update_campaign_montage(run_id, [edit.model_dump() for edit in body.edits])
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(500, f"Could not rebuild the campaign montage: {exc}") from exc
        return {
            "saved": True,
            "rendered": True,
            "outputs": len(result.get("renders", [])),
        }

    @app.post("/api/runs/{run_id}/campaign-ai-edit")
    def generate_campaign_ai_edit(run_id: str, body: CampaignAiEditRequest) -> dict:
        """Generate a fresh AI proposal without saving or rendering any edit."""
        run = _run_or_404(run_id)
        if not run["options"].get("campaign_mode"):
            raise HTTPException(400, "AI Edit is only available for campaign runs.")
        if run["status"] in {"queued", "running"}:
            raise HTTPException(409, "Wait for the campaign run to finish before using AI Edit.")
        if body.current_edit.rank < 1:
            raise HTTPException(400, "Choose a valid campaign clip.")
        select_file = pipeline.run_dir(run_id) / "work" / "select.json"
        if not select_file.is_file():
            raise HTTPException(404, "Campaign analysis is not available yet.")
        try:
            selection = json.loads(select_file.read_text(encoding="utf-8"))
            sources = selection.get("campaign_sources") or []
            if not sources:
                raise HTTPException(404, "Campaign source footage is not available.")
            proposal, notes = campaign.generate_ai_edit_proposal(
                get_llm(),
                str(run["options"].get("campaign_brief") or ""),
                body.current_edit.model_dump(),
                sources,
                body.creative_direction,
                candidate_edits=selection.get("campaign_edits") or [],
                source_analyses=selection.get("campaign_source_analyses") or [],
            )
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(503, f"AI Edit could not generate a proposal: {exc}") from exc
        return {"proposal": proposal, "notes": notes, "saved": False, "rendered": False}

    @app.post("/api/runs/{run_id}/campaign-music")
    def attach_campaign_music(run_id: str, file: UploadFile) -> dict:
        run = _run_or_404(run_id)
        if not run["options"].get("campaign_mode"):
            raise HTTPException(400, "Campaign music can only be attached to campaign runs.")
        if run["status"] in {"queued", "running"}:
            raise HTTPException(409, "Wait for the campaign run to finish before changing its music.")
        name = Path((file.filename or "campaign-music").replace("\\\\", "/")).name
        allowed_extensions = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".opus", ".wma", ".aiff"}
        is_audio = (file.content_type or "").startswith("audio/")
        has_audio_extension = Path(name).suffix.lower() in allowed_extensions
        if not is_audio and not has_audio_extension:
            raise HTTPException(400, "Choose an audio file for campaign music.")
        target = uploads_dir() / f"{db.new_id()}-{name}"
        _save_limited_upload(file, target, MAX_CAMPAIGN_MUSIC_UPLOAD_BYTES, "Campaign music upload")
        options = {**run["options"], "campaign_music_path": str(target)}
        db.update_run(run_id, options=options)
        return {"name": name, "attached": True}

    @app.post("/api/runs")
    def create_runs(body: CreateRuns) -> list[dict]:
        sources = [source.strip() for source in body.sources if source.strip()]
        if body.options.campaign_mode:
            if not body.options.campaign_brief.strip() and not body.options.campaign_url.strip():
                raise HTTPException(
                    400, "Paste a campaign link or campaign brief before starting the campaign editor."
                )
            if not 1 <= len(sources) <= 6:
                raise HTTPException(400, "A campaign edit needs between 1 and 6 source videos.")
            runs = [db.create_run(json.dumps(sources, ensure_ascii=False), body.options.model_dump())]
        else:
            runs = [db.create_run(source, body.options.model_dump()) for source in sources]
        if worker:
            worker.wake()
        return runs

    @app.get("/api/runs")
    def list_runs() -> list[dict]:
        return db.list_runs()

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str) -> dict:
        return run_detail(run_id)

    @app.get("/api/runs/{run_id}/campaign-music")
    def campaign_music_preview(run_id: str) -> FileResponse:
        """Stream the attached campaign soundtrack for in-editor listening."""
        run = _run_or_404(run_id)
        if not run["options"].get("campaign_mode"):
            raise HTTPException(400, "Music previews are only available for campaign runs.")
        music_path = run["options"].get("campaign_music_path")
        if not music_path:
            raise HTTPException(404, "No campaign music track is attached.")
        audio_file = Path(str(music_path))
        if not audio_file.is_file():
            raise HTTPException(404, "The attached campaign music file is missing.")
        media_type = mimetypes.guess_type(audio_file.name)[0] or "application/octet-stream"
        return FileResponse(
            audio_file,
            media_type=media_type,
            headers={"Cache-Control": "private, max-age=3600"},
        )

    @app.get("/api/runs/{run_id}/campaign-waveform")
    def campaign_waveform(run_id: str, bins: int = 640) -> dict[str, Any]:
        """Return cached normalized audio peaks for the campaign editor timeline."""
        run = _run_or_404(run_id)
        if not run["options"].get("campaign_mode"):
            raise HTTPException(400, "Waveforms are only available for campaign runs.")
        if bins < 4 or bins > 2000:
            raise HTTPException(400, "Waveform bins must be between 4 and 2000.")
        music_path = run["options"].get("campaign_music_path")
        if not music_path:
            raise HTTPException(404, "No campaign music track is attached.")
        audio_file = Path(str(music_path))
        if not audio_file.is_file():
            raise HTTPException(404, "The attached campaign music file is missing.")

        work_dir = pipeline.run_dir(run_id) / "work"
        work_dir.mkdir(parents=True, exist_ok=True)
        audio_stat = audio_file.stat()
        cache_path = work_dir / f"campaign-waveform-{bins}-{audio_stat.st_mtime_ns}-{audio_stat.st_size}.json"
        if cache_path.is_file():
            try:
                return json.loads(cache_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                cache_path.unlink(missing_ok=True)

        from clipyyy.media import ffmpeg_bin

        try:
            decoded = subprocess.run(
                [
                    ffmpeg_bin(),
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-i",
                    str(audio_file),
                    "-vn",
                    "-ac",
                    "1",
                    "-ar",
                    "4000",
                    "-f",
                    "s16le",
                    "pipe:1",
                ],
                capture_output=True,
                check=True,
                timeout=90,
            ).stdout
        except (OSError, subprocess.SubprocessError) as exc:
            raise HTTPException(500, f"Could not analyze the campaign soundtrack: {exc}") from exc

        samples = array("h")
        samples.frombytes(decoded[: len(decoded) - (len(decoded) % 2)])
        sample_count = len(samples)
        if sample_count == 0:
            raise HTTPException(422, "The attached soundtrack contains no decodable audio.")
        peaks = []
        for index in range(bins):
            start = index * sample_count // bins
            end = (index + 1) * sample_count // bins
            peak = max((abs(value) for value in samples[start:end]), default=0)
            peaks.append(round(peak / 32768, 4))
        result = {"duration_seconds": round(sample_count / 4000, 3), "peaks": peaks}
        cache_path.write_text(json.dumps(result), encoding="utf-8")
        return result

    @app.get("/api/runs/{run_id}/campaign-source")
    def campaign_source(run_id: str, source_index: int) -> FileResponse:
        """Stream one validated source video for in-editor playback."""
        run = _run_or_404(run_id)
        if not run["options"].get("campaign_mode"):
            raise HTTPException(400, "Source previews are only available for campaign runs.")
        if source_index < 0:
            raise HTTPException(400, "Choose a valid campaign source.")
        work_dir = pipeline.run_dir(run_id) / "work"
        source_file = work_dir / "download.json"
        if not source_file.is_file():
            raise HTTPException(404, "Campaign source footage is not available yet.")
        source_data = json.loads(source_file.read_text(encoding="utf-8"))
        select_file = work_dir / "select.json"
        selection_data = json.loads(select_file.read_text(encoding="utf-8")) if select_file.is_file() else {}
        source_items = selection_data.get("campaign_sources") or source_data.get("sources") or [source_data]
        if source_index >= len(source_items):
            raise HTTPException(404, "Campaign source not found.")
        video_path = Path(str(source_items[source_index].get("video_path") or ""))
        if not video_path.is_file():
            raise HTTPException(404, "Campaign source video is missing.")
        media_type = mimetypes.guess_type(video_path.name)[0] or "application/octet-stream"
        return FileResponse(
            video_path,
            media_type=media_type,
            headers={"Cache-Control": "private, max-age=3600"},
        )

    @app.get("/api/runs/{run_id}/campaign-frame")
    def campaign_frame(run_id: str, source_index: int, timestamp: float) -> FileResponse:
        """Return a cached still frame from one of this run's campaign source videos."""
        run = _run_or_404(run_id)
        if not run["options"].get("campaign_mode"):
            raise HTTPException(400, "Frame previews are only available for campaign runs.")
        if source_index < 0 or not math.isfinite(timestamp) or timestamp < 0:
            raise HTTPException(400, "Choose a valid source and non-negative timestamp.")

        work_dir = pipeline.run_dir(run_id) / "work"
        source_file = work_dir / "download.json"
        if not source_file.is_file():
            raise HTTPException(404, "Campaign source footage is not available yet.")
        source_data = json.loads(source_file.read_text(encoding="utf-8"))
        select_file = work_dir / "select.json"
        selection_data = json.loads(select_file.read_text(encoding="utf-8")) if select_file.is_file() else {}
        source_items = selection_data.get("campaign_sources") or source_data.get("sources") or [source_data]
        if source_index >= len(source_items):
            raise HTTPException(404, "Campaign source not found.")
        source = source_items[source_index]
        video_path = Path(str(source.get("video_path") or ""))
        duration = float(source.get("duration_seconds") or 0)
        if not video_path.is_file():
            raise HTTPException(404, "Campaign source video is missing.")
        if duration <= 0 or timestamp >= duration:
            raise HTTPException(400, "Preview timestamp is outside the source video.")

        preview_dir = work_dir / "campaign-thumbnails"
        preview_dir.mkdir(parents=True, exist_ok=True)
        cache_tick = round(timestamp * 10)
        preview_path = preview_dir / f"source-{source_index:02d}-{cache_tick:08d}.jpg"
        if not preview_path.is_file():
            from clipyyy.media import run_ffmpeg

            try:
                run_ffmpeg(
                    [
                        "-ss",
                        f"{timestamp:.3f}",
                        "-i",
                        str(video_path),
                        "-frames:v",
                        "1",
                        "-vf",
                        "scale=480:-2",
                        "-q:v",
                        "6",
                        str(preview_path),
                    ]
                )
            except Exception as exc:
                raise HTTPException(500, f"Could not create the campaign frame preview: {exc}") from exc
            if not preview_path.is_file() or preview_path.stat().st_size == 0:
                raise HTTPException(500, "FFmpeg did not produce a campaign frame preview.")
        return FileResponse(
            preview_path,
            media_type="image/jpeg",
            headers={"Cache-Control": "private, max-age=3600"},
        )

    @app.get("/api/runs/{run_id}/campaign-mask")
    def campaign_subject_mask(run_id: str, source_index: int, timestamp: float) -> FileResponse:
        """Return a cached alpha mask for live lyrics-behind-subject preview."""
        run = _run_or_404(run_id)
        if not run["options"].get("campaign_mode"):
            raise HTTPException(400, "Subject masks are only available for campaign runs.")
        if source_index < 0 or not math.isfinite(timestamp) or timestamp < 0:
            raise HTTPException(400, "Choose a valid source and non-negative timestamp.")

        work_dir = pipeline.run_dir(run_id) / "work"
        source_file = work_dir / "download.json"
        if not source_file.is_file():
            raise HTTPException(404, "Campaign source footage is not available yet.")
        source_data = json.loads(source_file.read_text(encoding="utf-8"))
        select_file = work_dir / "select.json"
        selection_data = json.loads(select_file.read_text(encoding="utf-8")) if select_file.is_file() else {}
        source_items = selection_data.get("campaign_sources") or source_data.get("sources") or [source_data]
        if source_index >= len(source_items):
            raise HTTPException(404, "Campaign source not found.")
        source = source_items[source_index]
        video_path = Path(str(source.get("video_path") or ""))
        duration = float(source.get("duration_seconds") or 0)
        if not video_path.is_file():
            raise HTTPException(404, "Campaign source video is missing.")
        if duration <= 0 or timestamp >= duration:
            raise HTTPException(400, "Preview timestamp is outside the source video.")

        # Four cached samples per second keep segmentation responsive while scrubbing.
        cache_tick = round(timestamp * 4)
        frame_timestamp = min(cache_tick / 4, max(0.0, duration - 0.001))
        mask_dir = work_dir / "campaign-subject-masks"
        mask_path = mask_dir / f"source-{source_index:02d}-{cache_tick:08d}.png"
        if not mask_path.is_file():
            from clipyyy.foreground import create_foreground_mask_frame

            try:
                create_foreground_mask_frame(video_path, frame_timestamp, mask_path)
            except Exception as exc:
                raise HTTPException(503, f"Could not prepare the subject mask: {exc}") from exc
        return FileResponse(
            mask_path,
            media_type="image/png",
            headers={"Cache-Control": "private, max-age=3600"},
        )

    @app.post("/api/runs/{run_id}/retry")
    def retry_run(run_id: str, body: RetryRun | None = None) -> dict:
        run = _run_or_404(run_id)
        if run["status"] in {"queued", "running"}:
            raise HTTPException(409, "Run is already queued or running")
        from_stage = body.from_stage if body else None
        if from_stage and from_stage not in pipeline.STAGE_NAMES:
            raise HTTPException(400, f"Unknown stage: {from_stage}")
        pipeline.retry(run_id, from_stage)
        if worker:
            worker.wake()
        return run_detail(run_id)

    @app.delete("/api/runs/{run_id}")
    def delete_run(run_id: str) -> dict:
        run = _run_or_404(run_id)
        if run["status"] == "running":
            raise HTTPException(409, "Wait for the run to finish before deleting it")
        pipeline.delete(run_id)
        return {"deleted": run_id}

    @app.get("/api/runs/{run_id}/download")
    def download_run(run_id: str) -> FileResponse:
        run = _run_or_404(run_id)
        clips = [c for c in db.list_clips(run_id) if c["status"] == "ready" and c["file_path"]]
        if not clips:
            raise HTTPException(404, "No clips to download yet")
        missing_files = [Path(c["file_path"]).name for c in clips if not Path(c["file_path"]).is_file()]
        if missing_files:
            preview = ", ".join(missing_files[:3])
            extra = f" and {len(missing_files) - 3} more" if len(missing_files) > 3 else ""
            raise HTTPException(
                409,
                f"Export unavailable: {len(missing_files)} clip file(s) are missing ({preview}{extra}). "
                "Re-render the run before downloading.",
            )
        export_dir = home() / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        name = f"clipyyy-{_safe(run['title'] or run_id)}-{run_id[:8]}.zip"
        archive_path = export_dir / name
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_STORED) as zf:
            used_names: set[str] = set()
            export_metadata: list[dict] = []
            for clip in clips:
                original_name = Path(clip["file_path"]).name
                archive_name = original_name
                if archive_name in used_names:
                    archive_name = f"clip-{int(clip.get('rank') or 0):02d}-{original_name}"
                    suffix = 2
                    while archive_name in used_names:
                        archive_name = f"clip-{int(clip.get('rank') or 0):02d}-{suffix}-{original_name}"
                        suffix += 1
                used_names.add(archive_name)
                zf.write(clip["file_path"], archive_name)
                export_metadata.append({**_clip_public(clip), "archive_filename": archive_name})
            zf.writestr("clips.json", json.dumps(export_metadata, indent=2, ensure_ascii=False))
            zf.writestr("POSTING-COPY.txt", _posting_copy(clips))
        return FileResponse(archive_path, filename=name, media_type="application/zip")

    # ── clips & publishing ───────────────────────────────────────────────────

    @app.get("/api/clips/{clip_id}/video")
    def clip_video(clip_id: str, download: bool = False) -> FileResponse:
        clip = db.get_clip(clip_id)
        if not clip or not clip["file_path"] or not Path(clip["file_path"]).exists():
            raise HTTPException(404, "Clip file not found")
        path = Path(clip["file_path"])
        return FileResponse(
            path,
            media_type="video/mp4",
            filename=path.name if download else None,
            content_disposition_type="attachment" if download else "inline",
        )

    @app.get("/api/clips/{clip_id}/poster")
    def clip_poster(clip_id: str) -> FileResponse:
        from clipyyy.render import make_poster, poster_path

        clip = db.get_clip(clip_id)
        if not clip or not clip["file_path"] or not Path(clip["file_path"]).exists():
            raise HTTPException(404, "Clip file not found")
        poster = poster_path(Path(clip["file_path"]))
        if not poster.exists():
            make_poster(Path(clip["file_path"]), 1.0)
        return FileResponse(poster, media_type="image/jpeg")

    @app.get("/api/buffer/channels")
    def buffer_channels() -> list[dict]:
        try:
            return BufferClient().channels()
        except PublishError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/buffer/organizations")
    def buffer_organizations() -> list[dict]:
        try:
            return BufferClient().organizations()
        except PublishError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/clips/{clip_id}/publish")
    def publish(clip_id: str, body: PublishRequest) -> list[dict]:
        try:
            return publish_clip(
                clip_id, body.channel_ids, body.mode, body.scheduled_at, body.text, body.title
            )
        except PublishError as exc:
            raise HTTPException(400, str(exc)) from exc

    # ── web UI ───────────────────────────────────────────────────────────────

    if (WEB_DIR / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=WEB_DIR / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            if path.startswith("api/"):
                raise HTTPException(404)
            candidate = (WEB_DIR / path).resolve()
            if path and candidate.is_file() and WEB_DIR.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(WEB_DIR / "index.html")

    return app


def run_detail(run_id: str) -> dict:
    run = _run_or_404(run_id)
    stage_rows = {s["name"]: s for s in db.list_stages(run_id)}
    stages = [
        {
            "name": name,
            "label": label,
            **{
                k: v
                for k, v in stage_rows.get(name, {}).items()
                if k in {"status", "error", "started_at", "finished_at"}
            },
        }
        for name, label, _ in pipeline.STAGES
    ]
    for stage in stages:
        stage.setdefault("status", "pending")
        if stage.get("started_at"):
            started = datetime.fromisoformat(stage["started_at"])
            finished = (
                datetime.fromisoformat(stage["finished_at"])
                if stage.get("finished_at")
                else datetime.now(started.tzinfo)
            )
            stage["duration_seconds"] = round(max(0.0, (finished - started).total_seconds()), 1)
    source_file = pipeline.run_dir(run_id) / "work" / "download.json"
    select_file = pipeline.run_dir(run_id) / "work" / "select.json"
    render_file = pipeline.run_dir(run_id) / "work" / "render.json"
    selection_data = {}
    campaign_plan = None
    campaign_edits = []
    campaign_original_edits = []
    campaign_concepts = []
    campaign_sources = []
    campaign_quality_checks = None
    if select_file.exists():
        selection_data = json.loads(select_file.read_text(encoding="utf-8"))
        campaign_plan = selection_data.get("campaign_plan")
        campaign_edits = selection_data.get("campaign_edits", [])
        campaign_original_edits = selection_data.get("campaign_original_edits") or campaign_edits
        campaign_concepts = selection_data.get("campaign_concepts", [])
    if source_file.exists() and run["options"].get("campaign_mode"):
        source_data = json.loads(source_file.read_text(encoding="utf-8"))
        source_items = selection_data.get("campaign_sources") or source_data.get("sources") or [source_data]
        campaign_sources = [
            {
                "index": index,
                "title": item.get("title") or f"Source {index + 1}",
                "duration_seconds": float(item.get("duration_seconds") or 0),
            }
            for index, item in enumerate(source_items)
        ]
    render_data = {}
    if render_file.exists():
        render_data = json.loads(render_file.read_text(encoding="utf-8"))
        campaign_quality_checks = render_data.get("quality_checks")
    filler_counts = {
        int(item["rank"]): int(item.get("filler_words_removed", 0))
        for item in render_data.get("renders", [])
        if item.get("rank") is not None
    }
    source_duration = None
    if source_file.exists():
        source_duration = json.loads(source_file.read_text(encoding="utf-8")).get("duration_seconds")
    return {
        **run,
        "source_duration": source_duration,
        "campaign_plan": campaign_plan,
        "campaign_edits": campaign_edits,
        "campaign_original_edits": campaign_original_edits,
        "campaign_concepts": campaign_concepts,
        "campaign_sources": campaign_sources,
        "campaign_quality_checks": campaign_quality_checks,
        "stages": stages,
        "clips": [
            {**_clip_public(c), "filler_words_removed": filler_counts.get(int(c["rank"]), 0)}
            for c in db.list_clips(run_id)
        ],
        "posts": db.list_posts(run_id=run_id),
    }


def _clip_public(clip: dict) -> dict:
    data = {k: v for k, v in clip.items() if k != "file_path"}
    data["filename"] = Path(clip["file_path"]).name if clip.get("file_path") else None
    data["video_url"] = f"/api/clips/{clip['id']}/video"
    data["poster_url"] = f"/api/clips/{clip['id']}/poster"
    data["download_url"] = f"/api/clips/{clip['id']}/video?download=true"
    return data


def _run_or_404(run_id: str) -> dict[str, Any]:
    run = db.get_run(run_id)
    if run is None:
        raise HTTPException(404, "Run not found")
    return run


def _safe(text: str) -> str:
    from clipyyy.render import slugify

    return slugify(text)


def _posting_copy(clips: list[dict]) -> str:
    """Build a plain-text, ready-to-copy posting sheet for the clips in an export."""
    sections = [
        "CLIPYYY — POSTING COPY",
        "Copy the title, caption and hashtags into your chosen social platform.",
    ]
    for clip in clips:
        title = str(clip.get("post_title") or clip.get("title") or "").strip()
        caption = str(clip.get("caption") or "").strip()
        hashtags = clip.get("hashtags") or []
        if isinstance(hashtags, str):
            hashtags = [hashtags] if hashtags.strip() else []
        tags = " ".join(str(tag).strip() for tag in hashtags if str(tag).strip())
        filename = Path(clip["file_path"]).name if clip.get("file_path") else "Video file"
        sections.extend(
            [
                "",
                "=" * 48,
                f"CLIP {clip.get('rank', '')}: {title or 'Untitled'}",
                f"Video: {filename}",
                "",
                "CAPTION",
                caption or "(No caption generated)",
                "",
                "HASHTAGS",
                tags or "(No hashtags generated)",
            ]
        )
    return "\n".join(sections).strip() + "\n"
