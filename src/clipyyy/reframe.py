"""Cut each clip out of the source and plan a crop that keeps the speaker's face in frame."""

from __future__ import annotations

import os
import subprocess
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from clipyyy.config import home
from clipyyy.media import ffmpeg_bin, probe, run_ffmpeg

SAMPLE_FPS = 1
DETECTION_WIDTH = 640
MIN_FACE_RATIO = 0.5
MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_detector/"
    "blaze_face_short_range/float16/latest/blaze_face_short_range.tflite"
)


@dataclass(slots=True)
class Face:
    x: float
    y: float
    width: float
    height: float


def prepare_clips(
    source: dict,
    timeline: dict,
    work_dir: Path,
    aspect: float,
    face_tracking: bool,
    broll: bool = False,
) -> dict:
    prepared = []
    source_path = Path(source["video_path"])
    width, height, _ = probe(source_path)
    for clip in timeline["clips"]:
        clip_dir = work_dir / f"clip-{clip['rank']:02d}"
        clip_dir.mkdir(parents=True, exist_ok=True)
        item = {"rank": clip["rank"]}
        if broll:
            # The legacy B-roll compositor needs a local speaker-only clip to build
            # alternating speaker/B-roll segments. Without B-roll, analyse the source
            # directly and skip this full-resolution intermediate encode.
            speaker_path = clip_dir / "speaker.mp4"
            run_ffmpeg(
                [
                    "-ss",
                    str(clip["start_seconds"]),
                    "-i",
                    str(source_path),
                    "-t",
                    str(clip["end_seconds"] - clip["start_seconds"]),
                    "-an",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "18",
                    str(speaker_path),
                ]
            )
            item["speaker_path"] = str(speaker_path)
            plan = (
                plan_crop(speaker_path, aspect)
                if face_tracking
                else center_plan(width, height, aspect, "face tracking off")
            )
        elif face_tracking:
            plan = plan_crop(source_path, aspect, clip["start_seconds"], clip["end_seconds"])
        else:
            plan = center_plan(width, height, aspect, "face tracking off")
        prepared.append({**item, **plan})
    return {"clips": prepared}


def plan_crop(
    clip_path: Path, aspect: float, start_seconds: float = 0.0, end_seconds: float | None = None
) -> dict:
    width, height, _ = probe(clip_path)
    samples = sample_faces(clip_path, width, height, start_seconds, end_seconds)
    if not samples:
        return center_plan(width, height, aspect, "face detector unavailable")
    tracked = [(t, f) for t, f in samples if f is not None]
    if len(tracked) / len(samples) < MIN_FACE_RATIO:
        return center_plan(width, height, aspect, f"faces found in {len(tracked)}/{len(samples)} frames")
    centers = smooth([((f.x + f.width / 2) * width, (f.y + f.height / 2) * height) for _, f in tracked])
    boxes = [
        {"t": round(t, 3), **face_box(f, width, height, cx, cy, aspect)}
        for (t, f), (cx, cy) in zip(tracked, centers, strict=True)
    ]
    return {"crop_mode": "face", "crop_boxes": boxes, "note": None}


def center_plan(width: int, height: int, aspect: float, note: str | None) -> dict:
    if width / max(height, 1) > aspect:
        crop_h, crop_w = height, round(height * aspect)
    else:
        crop_w, crop_h = width, round(width / aspect)
    box = {
        "t": 0.0,
        "x": (width - crop_w) // 2,
        "y": (height - crop_h) // 2,
        "width": max(2, crop_w),
        "height": max(2, crop_h),
    }
    return {"crop_mode": "center", "crop_boxes": [box], "note": note}


def face_box(face: Face, width: int, height: int, cx: float, cy: float, aspect: float) -> dict:
    crop_h = max(face.height * height * 3.2, height * 0.45)
    crop_w = crop_h * aspect
    if crop_w > width:
        crop_w, crop_h = float(width), width / aspect
    if crop_h > height:
        crop_h, crop_w = float(height), height * aspect
    x = clamp(cx - crop_w / 2, 0.0, width - crop_w)
    y = clamp(cy - crop_h / 2, 0.0, height - crop_h)
    return {"x": round(x), "y": round(y), "width": round(crop_w), "height": round(crop_h)}


def sample_faces(
    clip_path: Path,
    width: int,
    height: int,
    start_seconds: float = 0.0,
    end_seconds: float | None = None,
) -> list[tuple[float, Face | None]]:
    os.environ.setdefault("GLOG_minloglevel", "2")  # silence MediaPipe/LiteRT info logs
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
    try:
        import mediapipe as mp
        import numpy as np
    except ImportError:
        return []
    detector = mp.tasks.vision.FaceDetector.create_from_options(
        mp.tasks.vision.FaceDetectorOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=str(_model_path())),
            min_detection_confidence=0.5,
        )
    )
    sample_width, sample_height = detection_dimensions(width, height)
    frame_bytes = sample_width * sample_height * 3
    proc = subprocess.Popen(
        [
            ffmpeg_bin(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            str(start_seconds),
            "-i",
            str(clip_path),
            *(["-t", str(end_seconds - start_seconds)] if end_seconds is not None else []),
            "-an",
            "-vf",
            f"fps={SAMPLE_FPS},scale={sample_width}:{sample_height}",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "pipe:1",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    frame_detections: list[list[Face]] = []
    try:
        assert proc.stdout is not None
        while len(raw := proc.stdout.read(frame_bytes)) == frame_bytes:
            frame = np.frombuffer(raw, dtype=np.uint8).reshape((sample_height, sample_width, 3))
            result = detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=frame))
            faces = [
                Face(
                    d.bounding_box.origin_x / sample_width,
                    d.bounding_box.origin_y / sample_height,
                    d.bounding_box.width / sample_width,
                    d.bounding_box.height / sample_height,
                )
                for d in result.detections
            ]
            frame_detections.append(faces)
    finally:
        proc.stdout and proc.stdout.close()
        proc.wait()
        detector.close()
    tracked = track_primary_faces(frame_detections)
    return [(index / SAMPLE_FPS, face) for index, face in enumerate(tracked)]


def detection_dimensions(width: int, height: int) -> tuple[int, int]:
    """Downscale frames before face detection; coordinates remain normalized."""
    scale = min(1.0, DETECTION_WIDTH / max(width, 1))
    sample_width = max(2, round(width * scale / 2) * 2)
    sample_height = max(2, round(height * scale / 2) * 2)
    return sample_width, sample_height


def track_primary_faces(
    frame_detections: list[list[Face]], max_missing_frames: int = 2
) -> list[Face | None]:
    """Follow a geometrically consistent primary face instead of switching to every largest face."""
    tracked: list[Face | None] = []
    previous: Face | None = None
    missing = 0
    for faces in frame_detections:
        if not faces:
            tracked.append(None)
            missing += 1
            if missing > max_missing_frames:
                previous = None
            continue

        if previous is None:
            current = dominant(faces)
        else:
            previous_x = previous.x + previous.width / 2
            previous_y = previous.y + previous.height / 2
            largest_area = max(face.width * face.height for face in faces)

            def continuity_score(face: Face) -> float:
                center_x = face.x + face.width / 2
                center_y = face.y + face.height / 2
                distance = ((center_x - previous_x) ** 2 + (center_y - previous_y) ** 2) ** 0.5
                continuity = max(0.0, 1.0 - distance / 0.75)
                relative_size = (face.width * face.height / largest_area) ** 0.5
                return 0.72 * continuity + 0.28 * relative_size

            nearest_distance = min(
                (
                    (
                        (face.x + face.width / 2 - previous_x) ** 2
                        + (face.y + face.height / 2 - previous_y) ** 2
                    )
                    ** 0.5
                )
                for face in faces
            )
            current = dominant(faces) if nearest_distance > 0.45 else max(faces, key=continuity_score)

        tracked.append(current)
        previous = current
        missing = 0
    return tracked


def dominant(faces: list[Face]) -> Face | None:
    """Largest face, ties broken by closeness to the centre."""
    if not faces:
        return None
    return max(
        faces,
        key=lambda f: (
            f.width * f.height,
            -(((f.x + f.width / 2 - 0.5) ** 2 + (f.y + f.height / 2 - 0.5) ** 2) ** 0.5),
        ),
    )


def smooth(points: list[tuple[float, float]], window: int = 3) -> list[tuple[float, float]]:
    half = window // 2
    result = []
    for i in range(len(points)):
        chunk = points[max(0, i - half) : i + half + 1]
        result.append((sum(p[0] for p in chunk) / len(chunk), sum(p[1] for p in chunk) / len(chunk)))
    return result


def clamp(value: float, low: float, high: float) -> float:
    return low if low > high else max(low, min(high, value))


def _model_path() -> Path:
    path = home() / "models" / "blaze_face_short_range.tflite"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(MODEL_URL, path)
    return path
