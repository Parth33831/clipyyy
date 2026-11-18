from pathlib import Path

from clipyyy import media


def test_find_ffmpeg_prefers_a_build_that_can_draw_captions(tmp_path: Path, monkeypatch):
    plain = str(tmp_path / "usr-bin" / "ffmpeg")
    full = str(tmp_path / "ffmpeg-full" / "ffmpeg")
    candidates = [plain, full]
    has_libass = {plain: False, full: True}

    monkeypatch.setenv("PATH", "")
    monkeypatch.delenv("CLIPYYY_FFMPEG", raising=False)
    monkeypatch.delenv("HOMEBREW_PREFIX", raising=False)
    monkeypatch.setattr(media, "_candidates", lambda: candidates.copy())
    monkeypatch.setattr(media, "_has_libass", lambda binary: has_libass[binary])
    monkeypatch.setattr(
        media.shutil,
        "which",
        lambda name, path=None: str(Path(path) / name) if name == "ffprobe" and path else None,
    )
    media.find_ffmpeg.cache_clear()
    try:
        found = media.find_ffmpeg()
        assert (found.ffmpeg, found.ffprobe, found.libass) == (
            full,
            str(Path(full).parent / "ffprobe"),
            True,
        )

        candidates[:] = [plain]
        media.find_ffmpeg.cache_clear()
        found = media.find_ffmpeg()
        assert found.ffmpeg == plain and found.libass is False
        assert "ffmpeg" in media.install_hint()
    finally:
        media.find_ffmpeg.cache_clear()
