"""Environment checks shared by `clipyyy doctor` and the UI."""

from __future__ import annotations

from clipyyy.config import get_setting
from clipyyy.media import find_ffmpeg, install_hint
from clipyyy.publish import storage_configured
from clipyyy.source import js_runtime


def checks() -> list[dict]:
    found = find_ffmpeg()
    ffmpeg, libass = found.ffmpeg, found.libass
    provider = get_setting("llm_provider") or "openrouter"
    key_setting = {"openrouter": "openrouter_api_key", "gemini": "gemini_api_key"}.get(provider, "")
    llm_key = bool(get_setting(key_setting)) if key_setting else False
    llm_ready = provider == "ollama" or (bool(key_setting) and llm_key)
    llm_detail = (
        f"Ollama (local) · {get_setting('llm_model') or 'qwen2.5:1.5b'}"
        if provider == "ollama"
        else f"{provider} · {get_setting('llm_model')}"
        if llm_ready
        else f"add a {provider} API key or select the local Ollama provider"
    )
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
