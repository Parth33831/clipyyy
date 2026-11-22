"""Optional MediaPipe person segmentation for lyrics-behind-subject compositing.

The effect is deliberately opt-in: segmentation is CPU-intensive and requires the
MediaPipe selfie-segmentation model. Callers can fall back to ordinary lyrics if
the runtime or model is unavailable.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

from clipyyy.media import ffmpeg_bin, probe


def _read_exact(stream, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        chunk = stream.read(size - len(chunks))
        if not chunk:
            break
        chunks.extend(chunk)
    return bytes(chunks)


def create_foreground_mask(
    video_path: Path,
    mask_path: Path,
    *,
    processing_width: int = 540,
    fps: int = 12,
) -> Path:
    """Create a soft grayscale person mask video aligned to the supplied video."""
    try:
        import mediapipe as mp
    except ImportError as exc:
        raise RuntimeError(
            "Foreground lyrics need MediaPipe, which is not installed on this system."
        ) from exc

    selfie_module = getattr(getattr(mp, "solutions", None), "selfie_segmentation", None)
    if selfie_module is None:
        raise RuntimeError("This MediaPipe build does not include selfie segmentation.")

    source_width, source_height, duration = probe(video_path)
    if source_width <= 0 or source_height <= 0 or duration <= 0:
        raise RuntimeError("Could not read the campaign video dimensions for subject masking.")

    mask_width = min(processing_width, source_width)
    mask_width -= mask_width % 2
    mask_height = max(2, round((source_height * mask_width / source_width) / 2) * 2)
    mask_path.parent.mkdir(parents=True, exist_ok=True)

    decoder_command = [
        ffmpeg_bin(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(video_path),
        "-vf",
        f"fps={fps},scale={mask_width}:{mask_height}",
        "-an",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "pipe:1",
    ]
    encoder_command = [
        ffmpeg_bin(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "gray",
        "-s",
        f"{mask_width}x{mask_height}",
        "-r",
        str(fps),
        "-i",
        "pipe:0",
        "-an",
        "-c:v",
        "ffv1",
        "-level",
        "3",
        "-pix_fmt",
        "gray",
        str(mask_path),
    ]

    decoder = subprocess.Popen(decoder_command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    encoder = subprocess.Popen(encoder_command, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
    frame_bytes = mask_width * mask_height * 3
    frame_count = 0
    try:
        with selfie_module.SelfieSegmentation(model_selection=1) as segmenter:
            while decoder.stdout is not None and encoder.stdin is not None:
                raw_frame = _read_exact(decoder.stdout, frame_bytes)
                if len(raw_frame) != frame_bytes:
                    break
                frame = np.frombuffer(raw_frame, dtype=np.uint8).reshape((mask_height, mask_width, 3))
                result = segmenter.process(frame)
                segmentation = result.segmentation_mask
                if segmentation is None:
                    alpha = np.zeros((mask_height, mask_width), dtype=np.uint8)
                else:
                    # Keep a feathered edge to avoid a visibly cut-out silhouette.
                    alpha = np.clip((segmentation - 0.25) / 0.55, 0.0, 1.0)
                    alpha = np.round(alpha * 255).astype(np.uint8)
                encoder.stdin.write(alpha.tobytes())
                frame_count += 1
    finally:
        if decoder.stdout:
            decoder.stdout.close()
        if encoder.stdin:
            encoder.stdin.close()
        decoder_code = decoder.wait()
        encoder_code = encoder.wait()

    if decoder_code != 0 or encoder_code != 0 or frame_count == 0:
        mask_path.unlink(missing_ok=True)
        raise RuntimeError("Could not generate a complete foreground mask for this video.")
    return mask_path


def create_foreground_mask_frame(
    video_path: Path,
    timestamp: float,
    mask_path: Path,
    *,
    processing_width: int = 540,
) -> Path:
    """Create a cached PNG whose alpha hides the person and reveals lyrics behind them."""
    try:
        import mediapipe as mp
    except ImportError as exc:
        raise RuntimeError("Foreground lyrics need MediaPipe, which is not installed on this system.") from exc

    selfie_module = getattr(getattr(mp, "solutions", None), "selfie_segmentation", None)
    if selfie_module is None:
        raise RuntimeError("This MediaPipe build does not include selfie segmentation.")

    source_width, source_height, duration = probe(video_path)
    if source_width <= 0 or source_height <= 0 or duration <= 0 or timestamp < 0 or timestamp >= duration:
        raise RuntimeError("Could not read the requested frame for subject masking.")

    mask_width = min(processing_width, source_width)
    mask_width -= mask_width % 2
    mask_height = max(2, round((source_height * mask_width / source_width) / 2) * 2)
    decoded = subprocess.run(
        [
            ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-ss", f"{timestamp:.3f}",
            "-i", str(video_path), "-frames:v", "1", "-vf", f"scale={mask_width}:{mask_height}",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
        ],
        capture_output=True,
        check=True,
        timeout=45,
    ).stdout
    expected = mask_width * mask_height * 3
    if len(decoded) != expected:
        raise RuntimeError("FFmpeg did not return a complete frame for subject masking.")

    frame = np.frombuffer(decoded, dtype=np.uint8).reshape((mask_height, mask_width, 3))
    with selfie_module.SelfieSegmentation(model_selection=1) as segmenter:
        result = segmenter.process(frame)
    segmentation = result.segmentation_mask
    if segmentation is None:
        raise RuntimeError("The subject could not be detected in this frame.")

    # PNG alpha is opaque away from the person and transparent over the person.
    person = np.clip((segmentation - 0.25) / 0.55, 0.0, 1.0)
    alpha = np.round((1.0 - person) * 255).astype(np.uint8)
    rgba = np.full((mask_height, mask_width, 4), 255, dtype=np.uint8)
    rgba[:, :, 3] = alpha
    mask_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo",
            "-pix_fmt", "rgba", "-s", f"{mask_width}x{mask_height}", "-i", "pipe:0",
            "-frames:v", "1", str(mask_path),
        ],
        input=rgba.tobytes(),
        capture_output=True,
        check=True,
        timeout=45,
    )
    if not mask_path.is_file() or mask_path.stat().st_size == 0:
        raise RuntimeError("FFmpeg did not produce a subject mask image.")
    return mask_path
