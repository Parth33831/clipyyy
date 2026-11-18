"""Environment checks shared by `clipyyy doctor` and the UI."""

from __future__ import annotations

import httpx

from clipyyy.config import get_setting
from clipyyy.media import find_ffmpeg, install_hint
from clipyyy.publish import storage_configured
from clipyyy.source import js_runtime


def checks() -> list[dict]:
    found = find_ffmpeg()
    ffmpeg, libass = found.ffmpeg, found.libass
    model = get_setting("llm_model") or "qwen2.5vl:3b"
    try:
        response = httpx.get("http://127.0.0.1:11434/v1/models", timeout=2.0)
        response.raise_for_status()
        installed = {item.get("id") for item in response.json().get("data", [])}
        llm_ready = model in installed
        llm_detail = (
            f"Ollama (local) · {model}"
            if llm_ready
            else f"Ollama is running, but '{model}' is not installed. Choose an installed model in Settings."
        )
    except (httpx.HTTPError, ValueError):
        llm_ready = False
        llm_detail = "Ollama is not responding at 127.0.0.1:11434. Start the local Ollama service."
    runtime = js_runtime()
    return [
        _check(
            "ffmpeg",
            bool(ffmpeg and found.ffprobe),
            True,
            ffmpeg if ffmpeg and found.ffprobe else f"ffmpeg and ffprobe not found. {install_hint()}",
        ),
        _check(
            "captions",
            libass,
            True,
            "ffmpeg has libass"
            if libass
            else f"this ffmpeg can't draw captions (it has no libass). {install_hint()}",
        ),
        _check(
            "downloads",
            bool(runtime),
            False,
            f"yt-dlp uses {runtime.split(':')[0]} for YouTube"
            if runtime
            else "install deno or node so YouTube downloads work reliably",
        ),
        _check(
            "llm",
            llm_ready,
            True,
            llm_detail,
        ),
        _check(
            "broll",
            bool(get_setting("pexels_api_key")),
            False,
            "Pexels key set" if get_setting("pexels_api_key") else "optional: add a Pexels key",
        ),
        _check(
            "buffer",
            bool(get_setting("buffer_api_key")),
            False,
            "Buffer key set" if get_setting("buffer_api_key") else "optional: add a Buffer key",
        ),
        _check(
            "storage",
            storage_configured(),
            False,
            "S3 storage set" if storage_configured() else "optional: needed to publish to Buffer",
        ),
    ]


LABELS = {
    "ffmpeg": "FFmpeg",
    "captions": "Captions",
    "downloads": "YouTube downloads",
    "llm": "AI model",
    "broll": "B-roll",
    "buffer": "Buffer",
    "storage": "Storage",
}


def _check(name: str, ok: bool, required: bool, detail: str) -> dict:
    return {"name": name, "label": LABELS[name], "ok": ok, "required": required, "detail": detail}
