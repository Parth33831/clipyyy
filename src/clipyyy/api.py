"""HTTP API and web UI."""

from __future__ import annotations

import json
import os
import shutil
import zipfile
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from clipyyy import __version__, db, pipeline
from clipyyy.config import PACKAGE_DIR, SETTINGS, get_setting, home, mask, uploads_dir
from clipyyy.doctor import checks
from clipyyy.publish import BufferClient, PublishError, PublishMode, publish_clip
from clipyyy.worker import Worker

WEB_DIR = PACKAGE_DIR / "web"


class CreateRuns(BaseModel):
    sources: list[str] = Field(..., min_length=1, max_length=50)
    options: pipeline.ClipOptions = pipeline.ClipOptions()


class RetryRun(BaseModel):
    from_stage: str | None = None


class CampaignLyricsUpdate(BaseModel):
    lyrics: str = Field("", max_length=12000)
    lyrics_style: Literal[
        "dynamic", "cinematic", "minimal", "karaoke", "zoom", "bounce", "pulse", "glitch"
    ] = "dynamic"
    lyrics_color: str = Field("#FFFFFF", pattern=r"^#[0-9A-Fa-f]{6}$")
    highlight_color: str = Field("#00D7FF", pattern=r"^#[0-9A-Fa-f]{6}$")
    words_on_screen: Literal[1, 2, 3] = 3
    hook_text: str = Field("", max_length=160)
    include_hook: bool = False


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
        name = Path(file.filename or "upload.mp4").name
        target = uploads_dir() / f"{db.new_id()}-{name}"
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("wb") as fh:
            shutil.copyfileobj(file.file, fh, length=1024 * 1024)
        return {"source": str(target), "name": name}

    @app.put("/api/runs/{run_id}/campaign-lyrics")
    def update_campaign_lyrics(run_id: str, body: CampaignLyricsUpdate) -> dict:
        run = _run_or_404(run_id)
        if not run["options"].get("campaign_mode"):
            raise HTTPException(400, "Lyrics can only be edited on campaign runs.")
        if run["status"] in {"queued", "running"}:
            raise HTTPException(409, "Wait for the campaign run to finish before editing lyrics.")
        lyrics_unchanged = body.lyrics == run["options"].get("campaign_lyrics", "")
        options = {
            **run["options"],
            "campaign_lyrics": body.lyrics,
            "campaign_lyrics_source": (
                run["options"].get("campaign_lyrics_source", "Local Whisper draft")
                if lyrics_unchanged
                else "Creator-edited"
            ),
            # Preserve Whisper's word timings when only style or hook settings change.
            "campaign_lyric_words": (
                run["options"].get("campaign_lyric_words", []) if lyrics_unchanged else []
            ),
            "campaign_lyrics_style": body.lyrics_style,
            "campaign_lyrics_color": body.lyrics_color.upper(),
            "campaign_lyrics_highlight_color": body.highlight_color.upper(),
            "campaign_lyrics_words_on_screen": body.words_on_screen,
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

    @app.put("/api/runs/{run_id}/campaign-montage")
    def update_campaign_montage(run_id: str, body: CampaignMontageUpdate) -> dict:
        run = _run_or_404(run_id)
        if not run["options"].get("campaign_mode"):
            raise HTTPException(400, "Shot editing is only available for campaign runs.")
        if run["status"] in {"queued", "running"}:
            raise HTTPException(409, "Wait for the campaign run to finish before editing its shots.")
        try:
            result = pipeline.update_campaign_montage(
                run_id, [edit.model_dump() for edit in body.edits]
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(500, f"Could not rebuild the campaign montage: {exc}") from exc
        return {
            "saved": True,
            "rendered": True,
            "outputs": len(result.get("renders", [])),
        }

    @app.post("/api/runs/{run_id}/campaign-music")
    def attach_campaign_music(run_id: str, file: UploadFile) -> dict:
        run = _run_or_404(run_id)
        if not run["options"].get("campaign_mode"):
            raise HTTPException(400, "Campaign music can only be attached to campaign runs.")
        if run["status"] in {"queued", "running"}:
            raise HTTPException(409, "Wait for the campaign run to finish before changing its music.")
        name = Path(file.filename or "campaign-music").name
        allowed_extensions = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".opus", ".wma", ".aiff"}
        is_audio = (file.content_type or "").startswith("audio/")
        has_audio_extension = Path(name).suffix.lower() in allowed_extensions
        if not is_audio and not has_audio_extension:
            raise HTTPException(400, "Choose an audio file for campaign music.")
        target = uploads_dir() / f"{db.new_id()}-{name}"
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("wb") as fh:
            shutil.copyfileobj(file.file, fh, length=1024 * 1024)
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
        export_dir = home() / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        name = f"clipyyy-{_safe(run['title'] or run_id)}-{run_id[:8]}.zip"
        archive_path = export_dir / name
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_STORED) as zf:
            for clip in clips:
                zf.write(clip["file_path"], Path(clip["file_path"]).name)
            zf.writestr(
                "clips.json", json.dumps([_clip_public(c) for c in clips], indent=2, ensure_ascii=False)
            )
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
    campaign_sources = []
    campaign_quality_checks = None
    if select_file.exists():
        selection_data = json.loads(select_file.read_text(encoding="utf-8"))
        campaign_plan = selection_data.get("campaign_plan")
        campaign_edits = selection_data.get("campaign_edits", [])
        campaign_original_edits = selection_data.get("campaign_original_edits") or campaign_edits
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
