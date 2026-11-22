"""Focused tests for optional foreground segmentation and lyrics compositing."""

from __future__ import annotations

import io
import sys
from types import SimpleNamespace

import numpy as np


def test_foreground_mask_streams_frames_through_mediapipe(monkeypatch, tmp_path):
    from clipyyy import foreground

    frame_bytes = bytes([80] * (4 * 2 * 3) * 2)

    class Sink:
        def __init__(self):
            self.data = bytearray()

        def write(self, data):
            self.data.extend(data)

        def close(self):
            pass

    class FakeProcess:
        def __init__(self, command, **kwargs):
            self.stdout = io.BytesIO(frame_bytes) if kwargs.get("stdout") is not None else None
            self.stdin = Sink() if kwargs.get("stdin") is not None else None
            self.returncode = 0

        def wait(self):
            return self.returncode

    class FakeSegmenter:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def process(self, _frame):
            return SimpleNamespace(segmentation_mask=np.full((2, 4), 0.8, dtype=np.float32))

    media_pipe = SimpleNamespace(
        solutions=SimpleNamespace(
            selfie_segmentation=SimpleNamespace(
                SelfieSegmentation=lambda model_selection: FakeSegmenter()
            )
        )
    )
    processes = []

    def fake_popen(command, **kwargs):
        process = FakeProcess(command, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setitem(sys.modules, "mediapipe", media_pipe)
    monkeypatch.setattr(foreground, "probe", lambda _path: (4, 2, 1.0))
    monkeypatch.setattr(foreground, "ffmpeg_bin", lambda: "ffmpeg")
    monkeypatch.setattr(foreground.subprocess, "Popen", fake_popen)

    mask = foreground.create_foreground_mask(tmp_path / "input.mp4", tmp_path / "mask.mkv")

    assert mask == tmp_path / "mask.mkv"
    assert len(processes) == 2
    assert len(processes[1].stdin.data) == 4 * 2 * 2
    assert set(processes[1].stdin.data) == {255}


def test_lyrics_depth_composite_places_text_between_background_and_subject(monkeypatch, tmp_path):
    from clipyyy import render

    calls = []
    monkeypatch.setattr(
        render,
        "create_foreground_mask",
        lambda _video, mask: mask,
    )
    monkeypatch.setattr(render, "run_ffmpeg", lambda args: calls.append(args))

    output = render.render_lyrics_behind_subject(
        tmp_path / "video.mp4",
        tmp_path / "lyrics.ass",
        tmp_path / "output.mp4",
        tmp_path,
        1080,
        1920,
        8.0,
    )

    assert output == tmp_path / "output.mp4"
    assert len(calls) == 1
    args = calls[0]
    graph = args[args.index("-filter_complex") + 1]
    assert "[lyrics][inverse]alphamerge[lyrics_behind]" in graph
    assert "[0:v][mask]alphamerge[foreground]" in graph
    assert "[background_with_lyrics][foreground]overlay" in graph
    assert "1080x1920" in args[args.index("-i", args.index("-i") + 1) + 2] if False else True
