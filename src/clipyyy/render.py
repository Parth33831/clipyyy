"""Assemble the final clips: reframed speaker + optional B-roll, source audio, burned captions."""

from __future__ import annotations

import logging
import math
import re
import shutil
import subprocess
from array import array
from pathlib import Path
from statistics import median

from clipyyy.captions import ass_filter, clip_words, write_ass
from clipyyy.filler_words import filler_intervals
from clipyyy.foreground import create_foreground_mask
from clipyyy.media import ffmpeg_bin, has_audio, probe, run_ffmpeg

logger = logging.getLogger(__name__)

FPS = 30
AUDIO_NORMALIZATION_FILTER = "loudnorm=I=-16:TP=-1.5:LRA=11"
SIZES = {"9:16": (1080, 1920), "4:5": (1080, 1350), "1:1": (1080, 1080)}


def render_lyrics_behind_subject(
    video_path: Path,
    overlay_path: Path,
    output_path: Path,
    work_dir: Path,
    width: int,
    height: int,
    duration: float,
) -> Path:
    """Composite lyrics between the background and a segmented foreground person."""
    mask_path = work_dir / "lyrics-foreground-mask.mkv"
    create_foreground_mask(video_path, mask_path)
    transparent_canvas = f"color=c=black@0.0:s={width}x{height}:r={FPS}:d={duration:.3f}"
    graph = (
        f"[2:v]format=rgba,{ass_filter(overlay_path)}[lyrics];"
        f"[1:v]fps={FPS},scale={width}:{height}:flags=bicubic,format=gray[mask];"
        "[mask]negate[inverse];"
        "[lyrics][inverse]alphamerge[lyrics_behind];"
        "[0:v][lyrics_behind]overlay=shortest=1:format=auto[background_with_lyrics];"
        "[0:v][mask]alphamerge[foreground];"
        "[background_with_lyrics][foreground]overlay=shortest=1:format=auto[outv]"
    )
    run_ffmpeg(
        [
            "-i",
            str(video_path),
            "-i",
            str(mask_path),
            "-f",
            "lavfi",
            "-i",
            transparent_canvas,
            "-filter_complex",
            graph,
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
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    )
    return output_path


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
                normalize_audio=bool(options.get("normalize_audio", False)),
            )
            removed_fillers = 0
            if options.get("remove_filler_words") and transcript.get("language") == "en":
                source_intervals = filler_intervals(
                    transcript,
                    float(clip["start_seconds"]),
                    float(clip["end_seconds"]),
                    language=transcript.get("language", ""),
                )
                local_intervals = [
                    (start - float(clip["start_seconds"]), end - float(clip["start_seconds"]))
                    for start, end in source_intervals
                ]
                if local_intervals:
                    remove_timed_intervals(output, local_intervals)
                    removed_fillers = len(local_intervals)
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
                    "filler_words_removed": removed_fillers,
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
    normalize_audio: bool = False,
) -> None:
    width, height = size
    # The common no-B-roll case can be rendered directly from the source in one
    # FFmpeg pass. The old segment/concat path re-encoded every 3-second window and
    # then encoded the whole clip again for captions.
    if all(window["type"] == "speaker" for window in clip["windows"]):
        render_speaker_only(
            source_video, clip, prepared, work_dir, output, size, caption_style, normalize_audio
        )
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
        if normalize_audio:
            maps += ["-af", AUDIO_NORMALIZATION_FILTER]

    if caption_style and words:
        ass_path = write_ass(words, work_dir / "captions.ass", width, height, caption_style)
        # Veryfast keeps caption rendering practical on CPU-only laptops while CRF 20
        # preserves a clean social-video image.
        video_args = ["-vf", ass_filter(ass_path), "-c:v", "libx264", "-preset", "veryfast", "-crf", "20"]
    else:
        video_args = ["-c:v", "copy"]

    run_ffmpeg([*inputs, *maps, *video_args, "-shortest", "-movflags", "+faststart", str(output)])


def remove_timed_intervals(video: Path, intervals: list[tuple[float, float]]) -> None:
    """Remove matching time ranges from both streams in an already-rendered clip."""
    _, _, duration = probe(video)
    cuts = sorted(
        (max(0.0, start), min(duration, end))
        for start, end in intervals
        if end > start and start < duration and end > 0
    )
    if not cuts:
        return
    merged: list[list[float]] = []
    for start, end in cuts:
        if merged and start <= merged[-1][1] + 0.01:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    keep: list[tuple[float, float]] = []
    cursor = 0.0
    for start, end in merged:
        if start - cursor >= 0.04:
            keep.append((cursor, start))
        cursor = max(cursor, end)
    if duration - cursor >= 0.04:
        keep.append((cursor, duration))
    if not keep:
        return

    audio = has_audio(video)
    filters = []
    concat_labels = []
    for index, (start, end) in enumerate(keep):
        filters.append(f"[0:v]trim=start={start:.3f}:end={end:.3f},setpts=PTS-STARTPTS[v{index}]")
        concat_labels.append(f"[v{index}]")
        if audio:
            filters.append(f"[0:a]atrim=start={start:.3f}:end={end:.3f},asetpts=PTS-STARTPTS[a{index}]")
            concat_labels.append(f"[a{index}]")
    if audio:
        filters.append("".join(concat_labels) + f"concat=n={len(keep)}:v=1:a=1[vout][aout]")
    else:
        filters.append("".join(concat_labels) + f"concat=n={len(keep)}:v=1:a=0[vout]")

    temporary = video.with_name(f"{video.stem}-filler-cleaned{video.suffix}")
    args = ["-i", str(video), "-filter_complex", ";".join(filters), "-map", "[vout]"]
    if audio:
        args += ["-map", "[aout]", "-c:a", "aac", "-b:a", "160k"]
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
        str(temporary),
    ]
    run_ffmpeg(args)
    temporary.replace(video)


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
    normalize_audio: bool = False,
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
        if normalize_audio:
            args += ["-af", AUDIO_NORMALIZATION_FILTER]
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


def campaign_shot_filter(
    width: int,
    height: int,
    shot_index: int,
    camera_motion: bool = True,
    crop_boxes: list[dict] | None = None,
    source_width: int | None = None,
    source_height: int | None = None,
) -> str:
    """Create a campaign crop, preferring a tracked subject when face samples exist."""
    base_grade = ",eq=contrast=1.06:saturation=1.12"
    if crop_boxes and source_width and source_height:
        tracked_crop = crop_filter(crop_boxes, source_width, source_height, width / height)
        return f"{tracked_crop},scale={width}:{height},setsar=1,fps={FPS},format=yuv420p{base_grade}"
    if not camera_motion:
        return fill_filter(width, height) + base_grade

    # A small overscan gives the crop room to drift without exposing empty borders.
    zoom_width = round(width * 1.08)
    zoom_height = round(height * 1.08)
    phase = (shot_index % 4) * math.pi / 2
    return (
        f"scale={zoom_width}:{zoom_height}:force_original_aspect_ratio=increase,"
        f"crop={zoom_width}:{zoom_height},"
        f"crop={width}:{height}:"
        f"x='(iw-ow)*(0.5+0.24*sin(t*0.32+{phase:.4f}))':"
        f"y='(ih-oh)*(0.5+0.18*cos(t*0.26+{phase:.4f}))':eval=frame,"
        f"setsar=1,fps={FPS},format=yuv420p{base_grade}"
    )


def _campaign_subject_crop(source_path: Path, start: float, end: float, aspect: float):
    """Reuse the existing face tracker only when its model is already installed.

    Campaign rendering must not trigger an unexpected model download. If MediaPipe or
    its model is absent, callers retain the existing centre/Ken Burns fallback.
    """
    try:
        import importlib.util

        from clipyyy.config import home

        model_path = home() / "models" / "blaze_face_short_range.tflite"
        if not model_path.is_file() or importlib.util.find_spec("mediapipe") is None:
            return None, None, None
        from clipyyy.reframe import plan_crop

        source_width, source_height, _ = probe(source_path)
        plan = plan_crop(source_path, aspect, start, end)
        if plan.get("crop_mode") != "face" or not plan.get("crop_boxes"):
            return None, source_width, source_height
        return plan["crop_boxes"], source_width, source_height
    except Exception:
        # A failed optional detector must never make a campaign render fail.
        return None, None, None


def _campaign_audio_filter(
    duration: float,
    normalize_audio: bool,
    music_volume: float = 0.9,
    fade_in_seconds: float = 0.4,
    fade_out_seconds: float = 0.8,
) -> str:
    """Build the campaign music filter while preserving the historical mix defaults."""
    volume = max(0.0, min(2.0, float(music_volume)))
    fade_in = min(max(0.0, float(fade_in_seconds)), duration)
    fade_out = min(max(0.0, float(fade_out_seconds)), duration)
    filters = [f"volume={volume:.3f}"]
    if fade_in > 0:
        filters.append(f"afade=t=in:st=0:d={fade_in:.3f}")
    if fade_out > 0:
        filters.append(f"afade=t=out:st={max(0.0, duration - fade_out):.3f}:d={fade_out:.3f}")
    if normalize_audio:
        filters.append(AUDIO_NORMALIZATION_FILTER)
    return ",".join(filters)


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
    music_analysis = None
    if music_path:
        music_analysis = options.get("campaign_music_analysis") or analyze_campaign_music(
            music_path, target_duration
        )
    beat_times = music_analysis["beat_times"] if music_analysis else []
    music_start = float(music_analysis["best_start_seconds"]) if music_analysis else 0.0
    transition_style = options.get("campaign_transition_style", "auto")
    transition_seconds = 0.24
    use_transitions = transition_style in {"cinematic", "dynamic"} or (
        transition_style == "auto" and not beat_times
    )
    transition_names = (
        ["fade", "smoothleft", "smoothright", "wipeleft", "wiperight", "slideleft", "slideright"]
        if transition_style == "dynamic"
        else ["fade"]
    )
    hook = (
        str(options.get("campaign_hook_text") or campaign_plan.get("generated_hook") or "").strip()
        if options.get("include_campaign_hook", False)
        else ""
    )
    for edit in selection.get("campaign_edits", []):
        rank = edit["rank"]
        edit_dir = work_dir / f"campaign-edit-{rank:02d}"
        edit_dir.mkdir(parents=True, exist_ok=True)
        output = out_dir / f"campaign-{rank:02d}-{slugify(edit['title'])}.mp4"
        try:
            silent = edit_dir / "montage-silent.mp4"
            # Reuse the assembled montage for instant style-only changes.
            if not (options.get("reuse_campaign_montage") and silent.exists()):
                segments = []
                for shot_index, shot in enumerate(edit["shots"]):
                    source_index = int(shot["source_index"])
                    if not 0 <= source_index < len(sources):
                        raise ValueError(f"Shot {shot_index + 1} refers to a missing source video.")
                    source_path = Path(sources[source_index]["video_path"])
                    start = max(0.0, float(shot["start_seconds"]))
                    end = min(float(sources[source_index]["duration_seconds"]), float(shot["end_seconds"]))
                    duration = end - start
                    if music_analysis and duration >= 1.5:
                        elapsed = sum(probe(item)[2] for item in segments) if segments else 0.0
                        if use_transitions and segments:
                            elapsed -= (len(segments) - 1) * transition_seconds
                        overlap = transition_seconds if use_transitions and segments else 0.0
                        aligned_duration = select_music_cut_duration(
                            elapsed - overlap,
                            duration,
                            music_analysis,
                            selection.get("campaign_lyric_cues"),
                        )
                        if aligned_duration is not None:
                            end = min(
                                float(sources[source_index]["duration_seconds"]),
                                start + aligned_duration,
                            )
                            duration = end - start
                    if duration < 1.0:
                        continue
                    segment = edit_dir / f"shot-{shot_index:03d}.mp4"
                    crop_boxes = None
                    source_width = source_height = None
                    if options.get("face_tracking", True):
                        crop_boxes, source_width, source_height = _campaign_subject_crop(
                            source_path, start, end, width / height
                        )
                    vf = campaign_shot_filter(
                        width,
                        height,
                        shot_index,
                        options.get("campaign_camera_motion", True),
                        crop_boxes=crop_boxes,
                        source_width=source_width,
                        source_height=source_height,
                    )
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
                # Hard cuts preserve the musical transient at each selected beat.
                _crossfade_segments(
                    segments,
                    silent,
                    fade_seconds=transition_seconds if use_transitions else 0.0,
                    transition_names=transition_names,
                )
            _, _, duration = probe(silent)
            target_duration = float(campaign_plan.get("target_duration_seconds") or 0)
            if target_duration > 0 and abs(duration - target_duration) > 0.05:
                normalized = edit_dir / "montage-timed.mp4"
                _normalize_montage_duration(silent, normalized, duration, target_duration)
                silent = normalized
                _, _, duration = probe(silent)
            visual = silent
            lyrics_behind_subject_applied = False
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
                if options.get("campaign_lyric_words"):
                    write_campaign_word_lyrics(
                        options["campaign_lyric_words"],
                        duration,
                        overlay,
                        width,
                        height,
                        offset_seconds=music_start,
                        style=options.get("campaign_lyrics_style", "dynamic"),
                        text_color=options.get("campaign_lyrics_color", "#FFFFFF"),
                        highlight_color=options.get("campaign_lyrics_highlight_color", "#00D7FF"),
                        words_on_screen=options.get("campaign_lyrics_words_on_screen", 3),
                        beat_times=music_analysis.get("beat_times", []) if music_analysis else [],
                        position_x=options.get("campaign_lyrics_position_x", 50),
                        position_y=options.get("campaign_lyrics_position_y", 84),
                        scale_percent=options.get("campaign_lyrics_scale_percent", 100),
                        rotation_degrees=options.get("campaign_lyrics_rotation_degrees", 0),
                    )
                else:
                    write_campaign_lyrics(
                        lyrics,
                        duration,
                        overlay,
                        width,
                        height,
                        offset_seconds=music_start,
                        style=options.get("campaign_lyrics_style", "dynamic"),
                        text_color=options.get("campaign_lyrics_color", "#FFFFFF"),
                        highlight_color=options.get("campaign_lyrics_highlight_color", "#00D7FF"),
                        position_x=options.get("campaign_lyrics_position_x", 50),
                        position_y=options.get("campaign_lyrics_position_y", 84),
                        scale_percent=options.get("campaign_lyrics_scale_percent", 100),
                        rotation_degrees=options.get("campaign_lyrics_rotation_degrees", 0),
                    )
                captioned = edit_dir / "montage-lyrics.mp4"
                if options.get("campaign_lyrics_behind_subject", False):
                    try:
                        render_lyrics_behind_subject(
                            visual, overlay, captioned, edit_dir, width, height, duration
                        )
                        lyrics_behind_subject_applied = True
                    except Exception as exc:
                        logger.warning(
                            "Foreground lyric compositing unavailable; using normal lyric overlay: %s",
                            exc,
                        )
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
                else:
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
            text_overlays = [
                overlay
                for overlay in options.get("campaign_text_overlays", [])
                if int(overlay.get("rank", 1)) == int(clip["rank"])
            ]
            if text_overlays:
                text_overlay_path = edit_dir / "campaign-text-overlays.ass"
                write_campaign_text_overlays(
                    text_overlays, duration, text_overlay_path, width, height
                )
                overlaid = edit_dir / "montage-text-overlays.mp4"
                run_ffmpeg(
                    [
                        "-i",
                        str(visual),
                        "-vf",
                        ass_filter(text_overlay_path),
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
                        str(overlaid),
                    ]
                )
                visual = overlaid
            if music_path:
                music_input = []
                if music_analysis and music_analysis["duration_seconds"] - music_start < duration:
                    music_input = ["-stream_loop", "-1"]
                audio_filter = _campaign_audio_filter(
                    duration,
                    bool(options.get("normalize_audio")),
                    float(options.get("campaign_music_volume", 0.9)),
                    float(options.get("campaign_music_fade_in_seconds", 0.4)),
                    float(options.get("campaign_music_fade_out_seconds", 0.8)),
                )
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
                        audio_filter,
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
                    "lyrics_behind_subject": lyrics_behind_subject_applied,
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
            "lyrics_behind_subject_requested": bool(options.get("campaign_lyrics_behind_subject", False)),
            "lyrics_behind_subject_applied": (
                all(item.get("lyrics_behind_subject", False) for item in renders)
                if options.get("campaign_lyrics_behind_subject", False) and lyrics
                else False
            ),
            "camera_motion": bool(options.get("campaign_camera_motion", True)),
            "transition_style": transition_style,
            "music_track_added": bool(music_path),
            "audio_normalized": bool(music_path and options.get("normalize_audio", False)),
            "official_sound_required": official_sound_required,
            "beat_sync": (
                f"cuts guided by high-energy musical transients; estimated {music_analysis['bpm']} BPM"
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
                    "energy_sections": music_analysis.get("energy_sections", []),
                }
                if music_analysis
                else None
            ),
            "opening_hook": hook or None,
            "lyrics_style": options.get("campaign_lyrics_style", "dynamic") if lyrics else None,
            "official_platform_sound": (
                "select the campaign's official sound in the social app after export"
                if official_sound_required
                else "add manually if the campaign requires it"
            ),
        },
    }


def write_campaign_word_lyrics(
    words: list[dict],
    duration: float,
    path: Path,
    width: int,
    height: int,
    offset_seconds: float = 0.0,
    style: str = "dynamic",
    text_color: str = "#FFFFFF",
    highlight_color: str = "#00D7FF",
    words_on_screen: int = 3,
    beat_times: list[float] | None = None,
    position_x: int = 50,
    position_y: int = 84,
    scale_percent: int = 100,
    rotation_degrees: int = 0,
) -> Path:
    """Render rolling word captions with editable placement and music-beat accents."""
    from clipyyy.captions import _ass_color, _escape, _ts

    primary = _ass_color(text_color)
    accent = _ass_color(highlight_color)
    words_on_screen = max(1, min(3, int(words_on_screen)))
    position_x = max(5, min(95, int(position_x)))
    position_y = max(5, min(95, int(position_y)))
    scale_percent = max(50, min(200, int(scale_percent)))
    rotation_degrees = max(-30, min(30, int(rotation_degrees)))

    usable = [
        {
            "word": str(item.get("word", "")).strip(),
            "start": max(0.0, float(item.get("start", 0)) - offset_seconds),
            "end": max(0.0, float(item.get("end", 0)) - offset_seconds),
        }
        for item in words
        if str(item.get("word", "")).strip()
        and float(item.get("end", 0)) > offset_seconds
        and float(item.get("start", 0)) - offset_seconds < duration
    ]
    usable = [item for item in usable if item["end"] > item["start"]]
    if not usable:
        return write_campaign_lyrics(
            [],
            duration,
            path,
            width,
            height,
            style=style,
            text_color=text_color,
            highlight_color=highlight_color,
            position_x=position_x,
            position_y=position_y,
            scale_percent=scale_percent,
            rotation_degrees=rotation_degrees,
        )

    groups: list[list[dict]] = []
    current: list[dict] = []
    for word in usable:
        if current and (
            word["start"] - current[-1]["end"] > 0.55
            or len(current) >= words_on_screen
            or current[-1]["word"].endswith((".", "!", "?", "…"))
        ):
            groups.append(current)
            current = []
        current.append(word)
    if current:
        groups.append(current)

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
            f"Style: Default,Arial,{font_size},{primary},{accent},&H00000000,"
            f"&H64000000,1,0,0,0,100,100,0,0,1,4,2,2,{round(width * 0.07)},"
            f"{round(width * 0.07)},{round(height * 0.16)},1"
        ),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for index, group in enumerate(groups):
        group_offset = sum(len(previous) for previous in groups[:index])
        start = max(0.0, group[0]["start"])
        next_start = groups[index + 1][0]["start"] if index + 1 < len(groups) else duration
        end = min(duration, max(group[-1]["end"], next_start, start + 0.18))
        if end <= start:
            continue
        if style in {"dynamic", "zoom", "bounce", "pulse", "glitch"}:
            for word_index, item in enumerate(group):
                word_start = max(0.0, item["start"])
                next_start = group[word_index + 1]["start"] if word_index + 1 < len(group) else item["end"]
                word_end = min(duration, max(item["end"], next_start))
                if word_end <= word_start:
                    continue
                animation = (
                    f"{{\\fad(45,75)\\fscx55\\fscy55\\t(0,110,\\fscx118\\fscy118)"
                    f"\\t(110,220,\\fscx100\\fscy100)\\c{accent}\\bord4\\shad3}}"
                    if style in {"dynamic", "zoom"}
                    else f"{{\\fad(45,75)\\fscx88\\fscy125\\t(0,100,\\fscx108\\fscy92)"
                    f"\\t(100,200,\\fscx100\\fscy100)\\c{accent}\\bord4\\shad3}}"
                    if style == "bounce"
                    else f"{{\\fad(45,75)\\t(0,120,\\fscx115\\fscy115)"
                    f"\\t(120,240,\\fscx100\\fscy100)\\c{primary}\\bord4\\shad3}}"
                    if style == "pulse"
                    else f"{{\\fad(25,70)\\fscx85\\fscy112\\frz-3"
                    f"\\t(0,90,\\fscx110\\fscy92\\frz3)\\t(90,180,\\fscx100\\fscy100\\frz0)"
                    f"\\c{accent}\\bord4\\shad3}}"
                )
                if beat_times:
                    pulse_tags = []
                    for beat in beat_times:
                        relative_beat = float(beat) - offset_seconds
                        if word_start <= relative_beat < word_end:
                            beat_ms = max(0, round((relative_beat - word_start) * 1000))
                            pulse_tags.append(
                                f"\\t({beat_ms},{beat_ms + 75},\\fscx116\\fscy116)"
                                f"\\t({beat_ms + 75},{beat_ms + 180},\\fscx100\\fscy100)"
                            )
                    if pulse_tags:
                        animation = animation[:-1] + "".join(pulse_tags) + "}"
                # Animated word events alternate the selected main and highlight colors.
                # This keeps both chosen colors visible instead of hard-coding a cyan accent.
                visible_words = usable[
                    group_offset + word_index : group_offset + word_index + words_on_screen
                ]
                visible_text = " ".join(
                    f"{{\\c{primary if (group_offset + word_index + offset) % 2 == 0 else accent}}}"
                    f"{_escape(visible['word'])}{{\\c{primary}}}"
                    for offset, visible in enumerate(visible_words)
                )
                # Keep the selected words visible together; the window advances on each
                # recognized word boundary, while the current word keeps its own timing.
                script.append(
                    f"Dialogue: 0,{_ts(word_start)},{_ts(word_end)},Default,,0,0,0,,{animation}{visible_text}"
                )
            continue
        if style == "karaoke":
            pieces = []
            for word_index, item in enumerate(group):
                next_word_start = (
                    group[word_index + 1]["start"] if word_index + 1 < len(group) else item["end"]
                )
                word_end = min(end, max(item["end"], next_word_start))
                centiseconds = max(1, round((word_end - item["start"]) * 100))
                pieces.append(f"{{\\k{centiseconds}}}{_escape(item['word'])}")
            treatment = f"{{\\fad(60,100)\\c{primary}\\2c{accent}\\bord3\\shad2}}"
            text = " ".join(pieces)
        else:
            phrase = " ".join(item["word"] for item in group)
            treatment = (
                "{\\fad(80,100)\\fscx82\\fscy82\\t(0,150,\\fscx100\\fscy100)\\c&H00D7FF&\\bord4\\shad2}"
                if style == "dynamic"
                else "{\\fad(180,180)\\c&HFFFFFF&\\bord2\\shad3}"
                if style == "cinematic"
                else "{\\fad(100,120)\\c&HFFFFFF&\\bord2\\shad1}"
                if style == "minimal"
                else (
                    "{\\fad(50,100)\\fscx65\\fscy65\\t(0,120,\\fscx112\\fscy112)"
                    "\\t(120,240,\\fscx100\\fscy100)\\c&H00D7FF&\\bord4\\shad3}"
                )
                if style == "zoom"
                else (
                    "{\\fad(60,100)\\fscx90\\fscy125\\t(0,110,\\fscx105\\fscy95)"
                    "\\t(110,220,\\fscx100\\fscy100)\\c&H66E6FF&\\bord4\\shad3}"
                )
                if style == "bounce"
                else (
                    "{\\fad(60,100)\\fscx100\\fscy100\\t(0,180,\\fscx112\\fscy112)"
                    "\\t(180,360,\\fscx100\\fscy100)\\c&HFFFFFF&\\bord4\\shad3}"
                )
                if style == "pulse"
                else (
                    "{\\fad(35,90)\\fscx88\\fscy110\\frz-2\\t(0,90,\\fscx108\\fscy92\\frz2)"
                    "\\t(90,180,\\fscx100\\fscy100\\frz0)\\c&H00D7FF&\\bord4\\shad3}"
                )
            )
            text = _escape(phrase)
        script.append(f"Dialogue: 0,{_ts(start)},{_ts(end)},Default,,0,0,0,,{treatment}{text}")
    # Apply one editable transform to every timed lyric event. ASS positions are
    # expressed in the output canvas coordinate system, so they remain stable
    # across preview/export at the selected aspect ratio.
    x = round(width * position_x / 100)
    y = round(height * position_y / 100)
    transform = f"{{\\pos({x},{y})\\fscx{scale_percent}\\fscy{scale_percent}\\frz{rotation_degrees}}}"
    transformed_script = []
    for line in script:
        if line.startswith("Dialogue:"):
            fields = line.split(",", 9)
            if len(fields) == 10:
                fields[9] = transform + fields[9]
                line = ",".join(fields)
        transformed_script.append(line)
    script = transformed_script
    path.write_text("\n".join(script) + "\n", encoding="utf-8")
    return path


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
    style: str = "dynamic",
    text_color: str = "#FFFFFF",
    highlight_color: str = "#00D7FF",
    position_x: int = 50,
    position_y: int = 84,
    scale_percent: int = 100,
    rotation_degrees: int = 0,
) -> Path:
    """Burn timed lyrics with editable placement and dynamic styling."""
    from clipyyy.captions import _ass_color, _escape, _ts

    primary = _ass_color(text_color)
    accent = _ass_color(highlight_color)
    position_x = max(5, min(95, int(position_x)))
    position_y = max(5, min(95, int(position_y)))
    scale_percent = max(50, min(200, int(scale_percent)))
    rotation_degrees = max(-30, min(30, int(rotation_degrees)))

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
            if style == "karaoke":
                words = line.split()
                weights = [max(1, len(word)) for word in words]
                total_weight = sum(weights) or 1
                available_cs = max(len(words), round((end - start) * 100))
                remaining_cs = available_cs
                karaoke_text = []
                for word_index, word in enumerate(words):
                    word_cs = (
                        remaining_cs
                        if word_index == len(words) - 1
                        else max(1, round(available_cs * weights[word_index] / total_weight))
                    )
                    remaining_cs -= word_cs
                    karaoke_text.append(f"{{\\k{word_cs}}}{_escape(word)}")
                script.append(
                    dialogue
                    + "{\\fad(80,120)\\c&HFFFFFF&\\2c&H00D7FF&\\bord3\\shad2}"
                    + " ".join(karaoke_text)
                )
                continue
            treatment = (
                (
                    "{\\fad(90,120)\\fscx72\\fscy72\\t(0,170,\\fscx100\\fscy100)\\c&H00D7FF&\\bord4\\shad2}",
                    "{\\fad(90,120)\\fscx82\\fscy82\\t(0,150,\\fscx100\\fscy100)\\c&H66E6FF&\\bord4\\shad2}",
                    "{\\fad(90,120)\\fscx76\\fscy76\\t(0,190,\\fscx100\\fscy100)\\c&H99CCFF&\\bord4\\shad2}",
                )[index % 3]
                if style == "dynamic"
                else "{\\fad(220,220)\\c&HFFFFFF&\\bord2\\shad3\\fsp1}"
                if style == "cinematic"
                else "{\\fad(120,140)\\c&HFFFFFF&\\bord2\\shad1}"
            )
            script.append(dialogue + treatment + _escape(line))
    elif not has_lrc_timestamps:
        interval = duration / max(1, len(lines))
        for index, line in enumerate(lines):
            start = index * interval
            end = duration if index == len(lines) - 1 else (index + 1) * interval
            dialogue = f"Dialogue: 0,{_ts(start)},{_ts(end)},Default,,0,0,0,,"
            if style == "karaoke":
                words = line.split()
                weights = [max(1, len(word)) for word in words]
                total_weight = sum(weights) or 1
                available_cs = max(len(words), round((end - start) * 100))
                remaining_cs = available_cs
                karaoke_text = []
                for word_index, word in enumerate(words):
                    word_cs = (
                        remaining_cs
                        if word_index == len(words) - 1
                        else max(1, round(available_cs * weights[word_index] / total_weight))
                    )
                    remaining_cs -= word_cs
                    karaoke_text.append(f"{{\\k{word_cs}}}{_escape(word)}")
                treatment = "{\\fad(80,120)\\c&HFFFFFF&\\2c&H00D7FF&\\bord3\\shad2}"
                caption_text = treatment + " ".join(karaoke_text)
            else:
                treatment = (
                    "{\\fad(90,120)\\fscx75\\fscy75\\t(0,170,\\fscx100\\fscy100)\\c&H00D7FF&\\bord4\\shad2}"
                    if style == "dynamic"
                    else "{\\fad(220,220)\\c&HFFFFFF&\\bord2\\shad3\\fsp1}"
                    if style == "cinematic"
                    else "{\\fad(120,140)\\c&HFFFFFF&\\bord2\\shad1}"
                )
                caption_text = treatment + _escape(line)
            script.append(dialogue + caption_text)
    color_replacements = {
        "&H00FFFFFF&": primary,
        "&HFFFFFF&": primary,
        "&H0000D7FF&": accent,
        "&H00D7FF&": accent,
        "&H66E6FF&": accent,
        "&H99CCFF&": accent,
    }
    for index, line in enumerate(script):
        for original, chosen in color_replacements.items():
            line = line.replace(original, chosen)
        script[index] = line
    x = round(width * position_x / 100)
    y = round(height * position_y / 100)
    transform = f"{{\\pos({x},{y})\\fscx{scale_percent}\\fscy{scale_percent}\\frz{rotation_degrees}}}"
    transformed_script = []
    for line in script:
        if line.startswith("Dialogue:"):
            fields = line.split(",", 9)
            if len(fields) == 10:
                fields[9] = transform + fields[9]
                line = ",".join(fields)
        transformed_script.append(line)
    path.write_text("\n".join(transformed_script) + "\n", encoding="utf-8")
    return path



def write_campaign_text_overlays(
    overlays: list[dict],
    duration: float,
    path: Path,
    width: int,
    height: int,
) -> Path:
    """Create an independent ASS text layer with per-overlay timing and styling."""
    from clipyyy.captions import _ass_color, _escape, _ts

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
            "Style: Overlay,Arial,64,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,"
            "1,0,0,0,100,100,0,0,1,2,1,5,0,0,0,1"
        ),
        (
            "Style: OverlayBox,Arial,64,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,"
            "1,0,0,0,100,100,0,0,3,8,0,5,0,0,0,1"
        ),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for overlay in overlays[:30]:
        try:
            start = float(overlay.get("start_seconds", 0))
            end = float(overlay.get("end_seconds", 0))
            x_percent = max(5, min(95, int(overlay.get("position_x", 50))))
            y_percent = max(5, min(95, int(overlay.get("position_y", 50))))
            size_percent = max(60, min(200, int(overlay.get("font_size_percent", 100))))
            text_color = str(overlay.get("color") or "#FFFFFF")
            animation = str(overlay.get("animation") or "fade")
        except (TypeError, ValueError):
            continue
        text = str(overlay.get("text") or "").strip()
        if not text or not math.isfinite(start) or not math.isfinite(end):
            continue
        start = max(0.0, min(start, duration))
        end = max(start, min(end, duration))
        if end - start < 0.1:
            continue
        if not re.fullmatch(r"#[0-9A-Fa-f]{6}", text_color):
            text_color = "#FFFFFF"
        x = round(width * x_percent / 100)
        y = round(height * y_percent / 100)
        font_size = max(12, round(height * 0.052 * size_percent / 100))
        tags = f"{{\\an5\\pos({x},{y})\\fs{font_size}\\c{_ass_color(text_color)}}}"
        if animation == "fade":
            tags = tags[:-1] + r"\\fad(160,160)}"
        elif animation == "pop":
            tags = tags[:-1] + r"\\fscx70\\fscy70\\t(0,180,\\fscx100\\fscy100)\\fad(100,120)}"
        elif animation == "slide":
            offset_y = min(height - 1, y + round(height * 0.045))
            tags = f"{{\\an5\\move({x},{offset_y},{x},{y},0,220)\\fs{font_size}\\c{_ass_color(text_color)}\\fad(100,120)}}"
        style = "OverlayBox" if overlay.get("background", True) else "Overlay"
        escaped = r"\\N".join(_escape(part) for part in text.splitlines())
        script.append(
            f"Dialogue: 0,{_ts(start)},{_ts(end)},{style},,0,0,0,,{tags}{escaped}"
        )
    path.write_text("\\n".join(script) + "\\n", encoding="utf-8")
    return path


def _crossfade_segments(
    segments: list[Path],
    output: Path,
    fade_seconds: float = 0.28,
    transition_names: list[str] | None = None,
) -> None:
    """Join shots with a controlled sequence of short FFmpeg visual transitions."""
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
    allowed = {"fade", "smoothleft", "smoothright", "wipeleft", "wiperight", "slideleft", "slideright"}
    names = transition_names or ["fade"]
    names = [name if name in allowed else "fade" for name in names]
    filters = []
    previous = "[0:v]"
    total = durations[0]
    for index, duration in enumerate(durations[1:], start=1):
        output_label = f"[v{index}]"
        offset = max(0.0, total - fade_seconds)
        transition = names[(index - 1) % len(names)]
        filters.append(
            f"{previous}[{index}:v]xfade=transition={transition}:"
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


def _build_music_energy_sections(
    energy: list[float], frame_seconds: float, bucket_seconds: float = 0.5
) -> tuple[list[dict], list[dict]]:
    """Compress short-window RMS into normalized half-second energy and section summaries."""
    if not energy:
        return [], []
    stride = max(1, round(bucket_seconds / frame_seconds))
    buckets = [
        (index, sum(energy[index : index + stride]) / len(energy[index : index + stride]))
        for index in range(0, len(energy), stride)
        if energy[index : index + stride]
    ]
    values = [value for _, value in buckets]
    ordered = sorted(values)
    low = ordered[min(len(ordered) - 1, round((len(ordered) - 1) * 0.10))]
    high = ordered[min(len(ordered) - 1, round((len(ordered) - 1) * 0.90))]
    spread = high - low
    profile = [
        {
            "time_seconds": round((index + min(stride, len(energy) - index) / 2) * frame_seconds, 3),
            "energy": round(max(0.0, min(1.0, (value - low) / spread)), 4) if spread > 1e-9 else 0.5,
        }
        for index, value in buckets
    ]
    sections = []
    for point in profile:
        level = "low" if point["energy"] < 0.34 else "medium" if point["energy"] < 0.68 else "high"
        if sections and sections[-1]["level"] == level:
            sections[-1]["end_seconds"] = point["time_seconds"]
            sections[-1]["average_energy"] = round(
                (sections[-1]["average_energy"] * sections[-1]["samples"] + point["energy"])
                / (sections[-1]["samples"] + 1),
                4,
            )
            sections[-1]["samples"] += 1
        else:
            sections.append(
                {
                    "start_seconds": point["time_seconds"],
                    "end_seconds": point["time_seconds"],
                    "level": level,
                    "average_energy": point["energy"],
                    "samples": 1,
                }
            )
    for section in sections:
        section.pop("samples")
    return profile, sections


def select_music_cut_duration(
    elapsed_seconds: float,
    desired_duration: float,
    analysis: dict,
    lyric_cues: list[dict] | None = None,
) -> float | None:
    """Choose a nearby musical transient, preferring energetic beats without wild pacing jumps."""
    beats = analysis.get("beat_times") or []
    if not beats:
        return None
    strengths = analysis.get("beat_strengths") or []
    profile = analysis.get("energy_profile") or []
    music_start = float(analysis.get("best_start_seconds") or 0.0)
    lyric_boundaries = []
    for cue in lyric_cues or []:
        try:
            lyric_boundaries.extend([float(cue["start_seconds"]), float(cue["end_seconds"])])
        except (KeyError, TypeError, ValueError):
            continue
    candidates = []
    for index, beat in enumerate(beats):
        relative = float(beat) - music_start - elapsed_seconds
        if not 1.5 <= relative <= 5.0:
            continue
        strength = float(strengths[index]) if index < len(strengths) else 0.0
        energy = 0.5
        if profile:
            nearest = min(profile, key=lambda point: abs(float(point["time_seconds"]) - float(beat)))
            energy = max(0.0, min(1.0, float(nearest.get("energy", 0.5))))
        score = abs(relative - desired_duration) - 0.55 * energy - 0.35 * max(0.0, min(1.0, strength))
        if lyric_boundaries:
            cut_time = elapsed_seconds + relative
            lyric_distance = min(abs(cut_time - boundary) for boundary in lyric_boundaries)
            if lyric_distance <= 0.18:
                score -= 0.75 * (1.0 - lyric_distance / 0.18)
        candidates.append((score, relative))
    if not candidates:
        return None
    return round(min(candidates, key=lambda item: item[0])[1], 3)


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
    max_novelty = max(novelty, default=0.0)
    threshold = max(baseline * 2.2, max_novelty * 0.10)
    beats = []
    beat_strengths = []
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
                beat_strengths.append(round(value / max_novelty, 4) if max_novelty else 0.0)
                last = timestamp
    intervals = [
        second - first
        for first, second in zip(beats, beats[1:], strict=False)
        if 0.25 <= second - first <= 1.2
    ]
    beat_interval = median(intervals) if len(intervals) >= 4 else None
    bpm = round(60 / beat_interval) if beat_interval else None
    energy_profile, energy_sections = _build_music_energy_sections(energy, frame_seconds)
    return {
        "duration_seconds": round(track_duration, 2),
        "best_start_seconds": round(best_start, 3),
        "selected_section": f"{best_start:.1f}–{best_end:.1f}s",
        "beat_times": beats,
        "beat_strengths": beat_strengths,
        "energy_profile": energy_profile,
        "energy_sections": energy_sections,
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
