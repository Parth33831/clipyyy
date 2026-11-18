"""Assemble the final clips: reframed speaker + optional B-roll, source audio, burned captions."""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from statistics import median

from clipyyy.captions import ass_filter, clip_words, write_ass
from clipyyy.media import has_audio, probe, run_ffmpeg

FPS = 30
SIZES = {"9:16": (1080, 1920), "4:5": (1080, 1350), "1:1": (1080, 1080)}


def render_clips(
    source: dict,
    selection: dict,
    timeline: dict,
    prepared: dict,
    transcript: dict,
    work_dir: Path,
    out_dir: Path,
    options: dict,
) -> dict:
    width, height = SIZES[options["aspect_ratio"]]
    out_dir.mkdir(parents=True, exist_ok=True)
    prepared_by_rank = {c["rank"]: c for c in prepared["clips"]}
    selected_by_rank = {c["rank"]: c for c in selection["clips"]}
    renders = []
    add_captions = options["captions"] and not options.get("source_has_subtitles", False)
    for clip in timeline["clips"]:
        rank = clip["rank"]
        meta = selected_by_rank[rank]
        output = out_dir / f"clip-{rank:02d}-{slugify(meta['title'])}.mp4"
        clip_dir = work_dir / f"clip-{rank:02d}"
        try:
            clip_dir.mkdir(parents=True, exist_ok=True)
            words = clip_words(transcript, clip["start_seconds"], clip["end_seconds"])
            if add_captions and words:
                write_ass(words, clip_dir / "captions.ass", width, height, options["caption_style"])
            render_clip(
                source_video=Path(source["video_path"]),
                clip=clip,
                prepared=prepared_by_rank[rank],
                words=words,
                work_dir=clip_dir,
                output=output,
                size=(width, height),
                caption_style=options["caption_style"] if add_captions else None,
            )
            out_w, out_h, duration = probe(output)
            make_poster(output, min(1.0, duration / 2))
            renders.append(
                {
                    "rank": rank,
                    "status": "ready",
                    "file_path": str(output),
                    "width": out_w,
                    "height": out_h,
                    "duration_seconds": round(duration, 2),
                }
            )
        except Exception as exc:  # one bad clip should not sink the others
            renders.append({"rank": rank, "status": "failed", "error": str(exc)})
        finally:
            shutil.rmtree(clip_dir / "segments", ignore_errors=True)
    if not any(r["status"] == "ready" for r in renders):
        raise RuntimeError("Every clip failed to render: " + "; ".join(r.get("error", "") for r in renders))
    return {"renders": renders}


def render_clip(
    source_video: Path,
    clip: dict,
    prepared: dict,
    words: list[dict],
    work_dir: Path,
    output: Path,
    size: tuple[int, int],
    caption_style: str | None,
) -> None:
    width, height = size
    # The common no-B-roll case can be rendered directly from the source in one
    # FFmpeg pass. The old segment/concat path re-encoded every 3-second window and
    # then encoded the whole clip again for captions.
    if all(window["type"] == "speaker" for window in clip["windows"]):
        render_speaker_only(source_video, clip, prepared, work_dir, output, size, caption_style)
        return

    segments_dir = work_dir / "segments"
    segments_dir.mkdir(parents=True, exist_ok=True)
    speaker = Path(prepared["speaker_path"])

    segment_paths = []
    for window in clip["windows"]:
        segment = segments_dir / f"{window['index']:03d}.mp4"
        if window["type"] == "broll" and window.get("broll_path"):
            args = [
                "-stream_loop",
                "-1",
                "-i",
                window["broll_path"],
                "-t",
                str(window["duration"]),
                "-vf",
                fill_filter(width, height),
            ]
        else:
            box = nearest_box(window["start"], prepared["crop_boxes"])
            args = [
                "-ss",
                str(window["start"]),
                "-to",
                str(window["end"]),
                "-i",
                str(speaker),
                "-vf",
                f"crop={box['width']}:{box['height']}:{box['x']}:{box['y']},"
                f"scale={width}:{height},setsar=1,fps={FPS},format=yuv420p",
            ]
        run_ffmpeg([*args, "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", str(segment)])
        segment_paths.append(segment)

    concat_list = segments_dir / "list.txt"
    concat_list.write_text("".join(f"file '{p.resolve()}'\n" for p in segment_paths), encoding="utf-8")

    inputs = ["-f", "concat", "-safe", "0", "-i", str(concat_list)]
    maps = ["-map", "0:v:0"]
    if has_audio(source_video):
        inputs += [
            "-ss",
            str(clip["start_seconds"]),
            "-to",
            str(clip["end_seconds"]),
            "-i",
            str(source_video),
        ]
        maps += ["-map", "1:a:0", "-c:a", "aac", "-b:a", "160k"]

    if caption_style and words:
        ass_path = write_ass(words, work_dir / "captions.ass", width, height, caption_style)
        # Veryfast keeps caption rendering practical on CPU-only laptops while CRF 20
        # preserves a clean social-video image.
        video_args = ["-vf", ass_filter(ass_path), "-c:v", "libx264", "-preset", "veryfast", "-crf", "20"]
    else:
        video_args = ["-c:v", "copy"]

    run_ffmpeg([*inputs, *maps, *video_args, "-shortest", "-movflags", "+faststart", str(output)])


def poster_path(video: Path) -> Path:
    return video.with_suffix(".jpg")


def make_poster(video: Path, at: float) -> None:
    """A still frame for previews in the UI."""
    run_ffmpeg(
        [
            "-ss",
            str(at),
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-vf",
            "scale=540:-2",
            "-q:v",
            "4",
            str(poster_path(video)),
        ]
    )


def fill_filter(width: int, height: int) -> str:
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},"
        f"setsar=1,fps={FPS},format=yuv420p"
    )


def nearest_box(t: float, boxes: list[dict]) -> dict:
    return min(boxes, key=lambda b: abs(b["t"] - t))


def slugify(text: str, limit: int = 40) -> str:
    slug = re.sub(r"[^\w]+", "-", text.lower(), flags=re.UNICODE).strip("-")
    return slug[:limit].rstrip("-") or "clip"


def render_speaker_only(
    source_video: Path,
    clip: dict,
    prepared: dict,
    work_dir: Path,
    output: Path,
    size: tuple[int, int],
    caption_style: str | None,
) -> None:
    """Crop, scale, caption and encode a speaker-only clip in one FFmpeg pass."""
    width, height = size
    source_width, source_height, _ = probe(source_video)
    aspect = width / height
    boxes = prepared.get("crop_boxes") or []
    crop = crop_filter(boxes, source_width, source_height, aspect)
    filters = [crop, f"scale={width}:{height}", "setsar=1", f"fps={FPS}", "format=yuv420p"]
    if caption_style:
        ass_path = work_dir / "captions.ass"
        if ass_path.exists():
            filters.append(ass_filter(ass_path))
    duration = float(clip["end_seconds"]) - float(clip["start_seconds"])
    args = [
        "-ss",
        str(clip["start_seconds"]),
        "-i",
        str(source_video),
        "-t",
        str(duration),
        "-vf",
        ",".join(filters),
        "-map",
        "0:v:0",
    ]
    if has_audio(source_video):
        args += ["-map", "0:a:0", "-c:a", "aac", "-b:a", "160k"]
    args += [
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(output),
    ]
    run_ffmpeg(args)


def crop_filter(boxes: list[dict], source_width: int, source_height: int, aspect: float) -> str:
    """Build a smoothly interpolated crop path from face samples."""
    if not boxes:
        crop_h = source_height
        crop_w = min(source_width, round(crop_h * aspect))
        crop_h = min(source_height, round(crop_w / aspect))
        x = (source_width - crop_w) // 2
        y = (source_height - crop_h) // 2
        return f"crop={crop_w}:{crop_h}:{x}:{y}"

    ordered = sorted(boxes, key=lambda box: float(box.get("t", 0.0)))
    crop_w = min(source_width, max(2, round(median(float(box["width"]) for box in ordered))))
    crop_h = min(source_height, max(2, round(crop_w / aspect)))
    if crop_h > source_height:
        crop_h = source_height - source_height % 2
        crop_w = min(source_width, round(crop_h * aspect))
    crop_w -= crop_w % 2
    crop_h -= crop_h % 2

    points_x = []
    points_y = []
    for box in ordered:
        cx = float(box["x"]) + float(box["width"]) / 2
        cy = float(box["y"]) + float(box["height"]) / 2
        points_x.append((float(box.get("t", 0.0)), max(0.0, min(source_width - crop_w, cx - crop_w / 2))))
        points_y.append((float(box.get("t", 0.0)), max(0.0, min(source_height - crop_h, cy - crop_h / 2))))
    x_expr = _interpolate_expression(points_x)
    y_expr = _interpolate_expression(points_y)
    return f"crop={crop_w}:{crop_h}:{x_expr}:{y_expr}"


def _interpolate_expression(points: list[tuple[float, float]]) -> str:
    if len(points) <= 1:
        return f"{points[0][1]:.3f}" if points else "0"
    expression = f"{points[-1][1]:.3f}"
    for (t0, v0), (t1, v1) in reversed(list(zip(points, points[1:], strict=False))):
        if t1 <= t0:
            continue
        delta = t1 - t0
        segment = f"{v0:.3f}+({v1 - v0:.3f})*(t-{t0:.3f})/{delta:.3f}"
        expression = f"if(lt(t\\,{t1:.3f})\\,{segment}\\,{expression})"
    return expression


def render_campaign_montages(
    source: dict,
    selection: dict,
    work_dir: Path,
    out_dir: Path,
    options: dict,
) -> dict:
    """Render AI-planned multi-source campaign edits as finished, upload-ready MP4s."""
    width, height = SIZES[options["aspect_ratio"]]
    sources = source.get("sources") or [source]
    out_dir.mkdir(parents=True, exist_ok=True)
    renders = []
    lyrics = [line.strip() for line in options.get("campaign_lyrics", "").splitlines() if line.strip()]
    music_path = Path(options["campaign_music_path"]) if options.get("campaign_music_path") else None
    if music_path and not music_path.is_file():
        raise FileNotFoundError(f"Campaign music file not found: {music_path}")

    for edit in selection.get("campaign_edits", []):
        rank = edit["rank"]
        edit_dir = work_dir / f"campaign-edit-{rank:02d}"
        edit_dir.mkdir(parents=True, exist_ok=True)
        output = out_dir / f"campaign-{rank:02d}-{slugify(edit['title'])}.mp4"
        try:
            segments = []
            for shot_index, shot in enumerate(edit["shots"]):
                source_index = int(shot["source_index"])
                if not 0 <= source_index < len(sources):
                    raise ValueError(f"Shot {shot_index + 1} refers to a missing source video.")
                source_path = Path(sources[source_index]["video_path"])
                start = max(0.0, float(shot["start_seconds"]))
                end = min(float(sources[source_index]["duration_seconds"]), float(shot["end_seconds"]))
                duration = end - start
                if duration < 1.0:
                    continue
                segment = edit_dir / f"shot-{shot_index:03d}.mp4"
                vf = fill_filter(width, height) + ",eq=contrast=1.06:saturation=1.12"
                run_ffmpeg([
                    "-ss", f"{start:.3f}", "-i", str(source_path), "-t", f"{duration:.3f}",
                    "-vf", vf, "-an", "-c:v", "libx264", "-preset", "veryfast",
                    "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(segment),
                ])
                if segment.exists() and segment.stat().st_size:
                    segments.append(segment)
            if len(segments) < 3:
                raise RuntimeError("Fewer than three campaign shots could be rendered.")
            concat_list = edit_dir / "segments.txt"
            concat_list.write_text(
                "".join(f"file '{path.resolve().as_posix()}'\n" for path in segments),
                encoding="utf-8",
            )
            silent = edit_dir / "montage-silent.mp4"
            run_ffmpeg([
                "-f", "concat", "-safe", "0", "-i", str(concat_list),
                "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
                "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(silent),
            ])
            _, _, duration = probe(silent)
            visual = silent
            if lyrics:
                overlay = edit_dir / "campaign-lyrics.ass"
                write_campaign_lyrics(lyrics, duration, overlay, width, height)
                visual = edit_dir / "montage-lyrics.mp4"
                run_ffmpeg([
                    "-i", str(silent), "-vf", ass_filter(overlay), "-an",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(visual),
                ])
            if music_path:
                run_ffmpeg([
                    "-i", str(visual), "-stream_loop", "-1", "-i", str(music_path),
                    "-map", "0:v:0", "-map", "1:a:0", "-t", f"{duration:.3f}",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                    "-af", "volume=0.9,afade=t=in:st=0:d=0.4",
                    "-shortest", "-movflags", "+faststart", str(output),
                ])
            else:
                shutil.copy2(visual, output)
            out_w, out_h, final_duration = probe(output)
            make_poster(output, min(1.0, final_duration / 2))
            renders.append({
                "rank": rank, "status": "ready", "file_path": str(output),
                "width": out_w, "height": out_h, "duration_seconds": round(final_duration, 2),
                "audio": "user-provided campaign track" if music_path else "silent; add official campaign sound on the publishing platform if required",
                "lyrics_overlay": bool(lyrics),
            })
        except Exception as exc:
            renders.append({"rank": rank, "status": "failed", "error": str(exc)})
    if not any(item["status"] == "ready" for item in renders):
        raise RuntimeError("Every campaign edit failed to render: " + "; ".join(r.get("error", "") for r in renders))
    return {
        "renders": renders,
        "quality_checks": {
            "aspect_ratio": options["aspect_ratio"],
            "resolution": f"{width}x{height}",
            "lyrics_overlay": bool(lyrics),
            "music_track_added": bool(music_path),
            "official_platform_sound": "must be selected in the social app after export; never downloaded or impersonated",
        },
    }


def write_campaign_lyrics(lines: list[str], duration: float, path: Path, width: int, height: int) -> Path:
    """Burn only creator-supplied lyric/text lines, timed evenly over the montage."""
    from clipyyy.captions import _ass_color, _escape, _ts

    font_size = round(height * 0.047)
    script = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {width}", f"PlayResY: {height}",
        "WrapStyle: 0", "ScaledBorderAndShadow: yes", "", "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Default,Arial,{font_size},{_ass_color('FFFFFF')},&H000000FF,&H00000000,&H64000000,1,0,0,0,100,100,0,0,1,4,2,2,{round(width * 0.07)},{round(width * 0.07)},{round(height * 0.16)},1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    interval = duration / max(1, len(lines))
    for index, line in enumerate(lines):
        start = index * interval
        end = duration if index == len(lines) - 1 else (index + 1) * interval
        script.append(f"Dialogue: 0,{_ts(start)},{_ts(end)},Default,,0,0,0,,{{\\fad(180,180)}}{_escape(line)}")
    path.write_text("\n".join(script) + "\n", encoding="utf-8")
    return path
