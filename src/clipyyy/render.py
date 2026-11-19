"""Assemble the final clips: reframed speaker + optional B-roll, source audio, burned captions."""

from __future__ import annotations

import math
import re
import shutil
import subprocess
from array import array
from pathlib import Path
from statistics import median

from clipyyy.captions import ass_filter, clip_words, write_ass
from clipyyy.media import ffmpeg_bin, has_audio, probe, run_ffmpeg

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
    campaign_plan = options.get("campaign_plan") or {}
    official_sound_required = campaign_plan.get("official_platform_sound_required") is True
    # A creator-attached track is mixed into the preview/export even when the
    # campaign also requires selecting the official sound in TikTok at publish time.
    music_path = Path(options["campaign_music_path"]) if options.get("campaign_music_path") else None
    if music_path and not music_path.is_file():
        raise FileNotFoundError(f"Campaign music file not found: {music_path}")
    target_duration = float(campaign_plan.get("target_duration_seconds") or 30.0)
    music_analysis = analyze_campaign_music(music_path, target_duration) if music_path else None
    beat_times = music_analysis["beat_times"] if music_analysis else []
    music_start = float(music_analysis["best_start_seconds"]) if music_analysis else 0.0
    hook = str(campaign_plan.get("generated_hook") or "").strip()

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
                if beat_times and duration >= 1.5:
                    elapsed = sum(probe(item)[2] for item in segments) if segments else 0.0
                    desired_cut = elapsed + duration
                    candidates = [
                        beat - music_start
                        for beat in beat_times
                        if 1.5 <= beat - music_start - elapsed <= 5.0
                    ]
                    if candidates:
                        aligned_cut = min(candidates, key=lambda beat: abs(beat - desired_cut))
                        aligned_duration = aligned_cut - elapsed
                        if 1.5 <= aligned_duration <= 5.0:
                            end = min(
                                float(sources[source_index]["duration_seconds"]),
                                start + aligned_duration,
                            )
                            duration = end - start
                if duration < 1.0:
                    continue
                segment = edit_dir / f"shot-{shot_index:03d}.mp4"
                vf = fill_filter(width, height) + ",eq=contrast=1.06:saturation=1.12"
                run_ffmpeg(
                    [
                        "-ss",
                        f"{start:.3f}",
                        "-i",
                        str(source_path),
                        "-t",
                        f"{duration:.3f}",
                        "-vf",
                        vf,
                        "-an",
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
                        str(segment),
                    ]
                )
                if segment.exists() and segment.stat().st_size:
                    segments.append(segment)
            if len(segments) < 3:
                raise RuntimeError("Fewer than three campaign shots could be rendered.")
            silent = edit_dir / "montage-silent.mp4"
            # Hard cuts preserve the musical transient at each selected beat.
            _crossfade_segments(segments, silent, fade_seconds=0.0 if beat_times else 0.28)
            _, _, duration = probe(silent)
            target_duration = float(campaign_plan.get("target_duration_seconds") or 0)
            if target_duration > 0 and abs(duration - target_duration) > 0.05:
                normalized = edit_dir / "montage-timed.mp4"
                _normalize_montage_duration(silent, normalized, duration, target_duration)
                silent = normalized
                _, _, duration = probe(silent)
            visual = silent
            if hook:
                hook_overlay = edit_dir / "campaign-hook.ass"
                write_campaign_hook(hook, min(2.6, duration), hook_overlay, width, height)
                hooked = edit_dir / "montage-hook.mp4"
                run_ffmpeg(
                    [
                        "-i",
                        str(visual),
                        "-vf",
                        ass_filter(hook_overlay),
                        "-an",
                        "-c:v",
                        "libx264",
                        "-preset",
                        "veryfast",
                        "-crf",
                        "19",
                        "-pix_fmt",
                        "yuv420p",
                        "-movflags",
                        "+faststart",
                        str(hooked),
                    ]
                )
                visual = hooked
            if lyrics:
                overlay = edit_dir / "campaign-lyrics.ass"
                write_campaign_lyrics(lyrics, duration, overlay, width, height, offset_seconds=music_start)
                captioned = edit_dir / "montage-lyrics.mp4"
                run_ffmpeg(
                    [
                        "-i",
                        str(visual),
                        "-vf",
                        ass_filter(overlay),
                        "-an",
                        "-c:v",
                        "libx264",
                        "-preset",
                        "veryfast",
                        "-crf",
                        "19",
                        "-pix_fmt",
                        "yuv420p",
                        "-movflags",
                        "+faststart",
                        str(captioned),
                    ]
                )
                visual = captioned
            if music_path:
                music_input = []
                if music_analysis and music_analysis["duration_seconds"] - music_start < duration:
                    music_input = ["-stream_loop", "-1"]
                run_ffmpeg(
                    [
                        "-i",
                        str(visual),
                        *music_input,
                        "-ss",
                        f"{music_start:.3f}",
                        "-i",
                        str(music_path),
                        "-map",
                        "0:v:0",
                        "-map",
                        "1:a:0",
                        "-t",
                        f"{duration:.3f}",
                        "-c:v",
                        "copy",
                        "-c:a",
                        "aac",
                        "-b:a",
                        "192k",
                        "-af",
                        f"volume=0.9,afade=t=in:st=0:d=0.4,"
                        f"afade=t=out:st={max(0.0, duration - 0.8):.3f}:d=0.8",
                        "-shortest",
                        "-movflags",
                        "+faststart",
                        str(output),
                    ]
                )
            else:
                shutil.copy2(visual, output)
            out_w, out_h, final_duration = probe(output)
            make_poster(output, min(1.0, final_duration / 2))
            renders.append(
                {
                    "rank": rank,
                    "status": "ready",
                    "file_path": str(output),
                    "width": out_w,
                    "height": out_h,
                    "duration_seconds": round(final_duration, 2),
                    "audio": (
                        "user-provided campaign track included; select the official campaign sound "
                        "separately in TikTok if required"
                        if music_path and official_sound_required
                        else "user-provided campaign track included"
                        if music_path
                        else "silent; add official campaign sound on the publishing platform if required"
                    ),
                    "lyrics_overlay": bool(lyrics),
                    "beat_synced": bool(beat_times),
                    "music_start_seconds": round(music_start, 2),
                    "music_bpm_estimate": music_analysis.get("bpm") if music_analysis else None,
                }
            )
        except Exception as exc:
            renders.append({"rank": rank, "status": "failed", "error": str(exc)})
    failed = [item for item in renders if item["status"] != "ready"]
    if failed:
        errors = "; ".join(item.get("error", "") for item in failed)
        raise RuntimeError("Campaign export incomplete; retry after fixing: " + errors)
    return {
        "renders": renders,
        "quality_checks": {
            "aspect_ratio": options["aspect_ratio"],
            "resolution": f"{width}x{height}",
            "output_count": len(renders),
            "all_outputs_rendered": all(item["status"] == "ready" for item in renders),
            "rendered_duration_range": (
                f"{min(item['duration_seconds'] for item in renders):.1f}–"
                f"{max(item['duration_seconds'] for item in renders):.1f} seconds"
            ),
            "lyrics_overlay": bool(lyrics),
            "music_track_added": bool(music_path),
            "official_sound_required": official_sound_required,
            "beat_sync": (
                f"cuts aligned to detected musical transients; estimated {music_analysis['bpm']} BPM"
                if music_analysis and beat_times and music_analysis.get("bpm")
                else "track analysed, but reliable beat transients were not detected"
                if music_analysis
                else "not applied (no local track attached)"
            ),
            "music_analysis": (
                {
                    "duration_seconds": music_analysis["duration_seconds"],
                    "selected_start_seconds": round(music_start, 2),
                    "selected_section": music_analysis["selected_section"],
                    "estimated_bpm": music_analysis.get("bpm"),
                    "detected_beats": len(beat_times),
                }
                if music_analysis
                else None
            ),
            "opening_hook": hook or None,
            "official_platform_sound": (
                "select the campaign's official sound in the social app after export"
                if official_sound_required
                else "add manually if the campaign requires it"
            ),
        },
    }


def _normalize_montage_duration(
    source: Path, output: Path, current_duration: float, target_duration: float
) -> Path:
    """Trim or freeze the final frame so a montage matches its requested duration."""
    if target_duration <= 0:
        raise ValueError("Target montage duration must be positive.")
    padding = max(0.0, target_duration - current_duration)
    video_filter = (
        f"tpad=stop_mode=clone:stop_duration={padding:.3f},"
        f"trim=duration={target_duration:.3f},setpts=PTS-STARTPTS"
    )
    run_ffmpeg(
        [
            "-i",
            str(source),
            "-vf",
            video_filter,
            "-an",
            "-t",
            f"{target_duration:.3f}",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "19",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(output),
        ]
    )
    return output


def write_campaign_lyrics(
    lines: list[str],
    duration: float,
    path: Path,
    width: int,
    height: int,
    offset_seconds: float = 0.0,
) -> Path:
    """Burn only creator-supplied lyric/text lines, timed evenly over the montage."""
    from clipyyy.captions import _ass_color, _escape, _ts

    font_size = round(height * 0.047)
    script = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        (
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
            "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
            "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding"
        ),
        (
            f"Style: Default,Arial,{font_size},{_ass_color('FFFFFF')},&H000000FF,"
            f"&H00000000,&H64000000,1,0,0,0,100,100,0,0,1,4,2,2,"
            f"{round(width * 0.07)},{round(width * 0.07)},{round(height * 0.16)},1"
        ),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    timed_lines = []
    for line in lines:
        match = re.match(r"^\[(\d{1,2}):(\d{2})(?:\.(\d{1,2}))?\]\s*(.+)$", line)
        if match:
            minutes, seconds, fraction, text = match.groups()
            centiseconds = int((fraction or "0").ljust(2, "0")[:2])
            relative_start = int(minutes) * 60 + int(seconds) + centiseconds / 100 - offset_seconds
            if 0 <= relative_start < duration:
                timed_lines.append((relative_start, text))
    has_lrc_timestamps = any(re.match(r"^\[\d{1,2}:\d{2}(?:\.\d{1,2})?\]", line) for line in lines)
    if timed_lines:
        for index, (start, line) in enumerate(timed_lines):
            end = timed_lines[index + 1][0] if index + 1 < len(timed_lines) else duration
            start = max(0.0, min(start, duration))
            end = min(duration, max(start + 0.2, min(end, duration)))
            dialogue = f"Dialogue: 0,{_ts(start)},{_ts(end)},Default,,0,0,0,,"
            script.append(dialogue + f"{{\\fad(100,120)}}{_escape(line)}")
    elif not has_lrc_timestamps:
        interval = duration / max(1, len(lines))
        for index, line in enumerate(lines):
            start = index * interval
            end = duration if index == len(lines) - 1 else (index + 1) * interval
            dialogue = f"Dialogue: 0,{_ts(start)},{_ts(end)},Default,,0,0,0,,"
            script.append(dialogue + f"{{\\fad(180,180)}}{_escape(line)}")
    path.write_text("\n".join(script) + "\n", encoding="utf-8")
    return path


def _crossfade_segments(segments: list[Path], output: Path, fade_seconds: float = 0.28) -> None:
    """Join shots with short visual dissolves instead of abrupt hard cuts."""
    if len(segments) < 2:
        raise ValueError("At least two shots are required for a campaign montage.")
    durations = [probe(segment)[2] for segment in segments]
    inputs: list[str] = []
    for segment in segments:
        inputs.extend(["-i", str(segment)])
    if fade_seconds <= 0:
        concat_inputs = "".join(f"[{index}:v]" for index in range(len(segments)))
        run_ffmpeg(
            [
                *inputs,
                "-filter_complex",
                f"{concat_inputs}concat=n={len(segments)}:v=1:a=0[outv]",
                "-map",
                "[outv]",
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "19",
                "-pix_fmt",
                "yuv420p",
                "-r",
                str(FPS),
                "-movflags",
                "+faststart",
                str(output),
            ]
        )
        return
    filters = []
    previous = "[0:v]"
    total = durations[0]
    for index, duration in enumerate(durations[1:], start=1):
        output_label = f"[v{index}]"
        offset = max(0.0, total - fade_seconds)
        filters.append(
            f"{previous}[{index}:v]xfade=transition=fade:"
            f"duration={fade_seconds}:offset={offset:.3f}{output_label}"
        )
        previous = output_label
        total += duration - fade_seconds
    run_ffmpeg(
        [
            *inputs,
            "-filter_complex",
            ";".join(filters),
            "-map",
            previous,
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "19",
            "-pix_fmt",
            "yuv420p",
            "-r",
            str(FPS),
            "-movflags",
            "+faststart",
            str(output),
        ]
    )


def detect_music_beat_interval(path: Path) -> float | None:
    """Estimate a beat interval from short-window audio energy; return None when uncertain."""
    try:
        result = subprocess.run(
            [
                ffmpeg_bin(),
                "-v",
                "error",
                "-i",
                str(path),
                "-ac",
                "1",
                "-ar",
                "11025",
                "-f",
                "f32le",
                "pipe:1",
            ],
            capture_output=True,
            timeout=90,
            check=False,
        )
        if result.returncode or len(result.stdout) < 11025 * 4:
            return None
        samples = array("f")
        samples.frombytes(result.stdout[: len(result.stdout) - (len(result.stdout) % 4)])
        window = 551
        energy = []
        for offset in range(0, len(samples) - window, window):
            chunk = samples[offset : offset + window]
            energy.append(sum(value * value for value in chunk) / window)
        if len(energy) < 20:
            return None
        baseline = median(energy)
        threshold = max(baseline * 1.5, 1e-7)
        peaks = []
        for index in range(1, len(energy) - 1):
            if (
                energy[index] >= threshold
                and energy[index] >= energy[index - 1]
                and energy[index] > energy[index + 1]
            ):
                timestamp = index * window / 11025
                if not peaks or timestamp - peaks[-1] >= 0.25:
                    peaks.append(timestamp)
        intervals = [b - a for a, b in zip(peaks, peaks[1:], strict=False) if 0.30 <= b - a <= 1.20]
        if len(intervals) < 4:
            return None
        estimate = median(intervals)
        return round(estimate, 4) if 0.30 <= estimate <= 1.20 else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def analyze_campaign_music(path: Path, target_duration: float) -> dict:
    """Analyse the complete local track and choose its most energetic usable section."""
    result = subprocess.run(
        [
            ffmpeg_bin(),
            "-v",
            "error",
            "-i",
            str(path),
            "-ac",
            "1",
            "-ar",
            "11025",
            "-f",
            "f32le",
            "pipe:1",
        ],
        capture_output=True,
        timeout=180,
        check=False,
    )
    if result.returncode or len(result.stdout) < 11025 * 4:
        raise RuntimeError("Could not decode the attached campaign music for analysis.")
    samples = array("f")
    samples.frombytes(result.stdout[: len(result.stdout) - (len(result.stdout) % 4)])
    sample_rate = 11025
    window = 551
    energy = []
    for offset in range(0, len(samples) - window, window):
        chunk = samples[offset : offset + window]
        energy.append(math.sqrt(sum(value * value for value in chunk) / window))
    frame_seconds = window / sample_rate
    track_duration = len(samples) / sample_rate
    if not energy:
        raise RuntimeError("The attached campaign music contains no analysable audio.")
    target = min(max(1.0, float(target_duration)), track_duration)
    frame_count = max(1, round(target / frame_seconds))
    stride = max(1, round(0.5 / frame_seconds))
    if len(energy) <= frame_count:
        best_frame = 0
    else:
        best_frame = max(
            range(0, len(energy) - frame_count + 1, stride),
            key=lambda start: sum(energy[start : start + frame_count]) / frame_count,
        )
    best_start = best_frame * frame_seconds
    best_end = min(track_duration, best_start + target)

    novelty = [max(0.0, energy[index] - energy[index - 1]) for index in range(1, len(energy))]
    baseline = median(novelty) if novelty else 0.0
    threshold = max(baseline * 2.2, max(novelty, default=0.0) * 0.10)
    beats = []
    last = -1.0
    for index in range(1, len(novelty) - 1):
        value = novelty[index]
        timestamp = (index + 1) * frame_seconds
        if (
            value >= threshold
            and value >= novelty[index - 1]
            and value > novelty[index + 1]
            and timestamp - last >= 0.24
        ):
            if best_start <= timestamp <= best_end:
                beats.append(round(timestamp, 3))
                last = timestamp
    intervals = [
        second - first
        for first, second in zip(beats, beats[1:], strict=False)
        if 0.25 <= second - first <= 1.2
    ]
    beat_interval = median(intervals) if len(intervals) >= 4 else None
    bpm = round(60 / beat_interval) if beat_interval else None
    return {
        "duration_seconds": round(track_duration, 2),
        "best_start_seconds": round(best_start, 3),
        "selected_section": f"{best_start:.1f}–{best_end:.1f}s",
        "beat_times": beats,
        "beat_interval_seconds": round(beat_interval, 4) if beat_interval else None,
        "bpm": bpm,
    }


def write_campaign_hook(text: str, duration: float, path: Path, width: int, height: int) -> Path:
    """Create a bold, short opening hook overlay."""
    from clipyyy.captions import _ass_color, _escape, _ts

    font_size = round(height * 0.065)
    script = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        (
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
            "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
            "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding"
        ),
        (
            f"Style: Default,Arial,{font_size},{_ass_color('FFFFFF')},&H000000FF,&H00000000,"
            f"&H64000000,1,0,0,0,100,100,0,0,1,5,2,5,{round(width * 0.08)},"
            f"{round(width * 0.08)},{round(height * 0.24)},1"
        ),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        f"Dialogue: 0,0:00:00.00,{_ts(duration)},Default,,0,0,0,,{{\\fad(120,180)}}{_escape(text)}",
    ]
    path.write_text("\n".join(script) + "\n", encoding="utf-8")
    return path
