import base64
import json

import httpx

from clipyyy.llm import PROVIDERS, OpenAICompatibleLLM
from clipyyy.vision import sample_frames


def test_vision_request_sends_timestamped_image_data(tmp_path):
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"fake-jpeg-bytes")
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"frames": []}'}}]})

    llm = OpenAICompatibleLLM(
        PROVIDERS["gemini"],
        "test-key",
        "gemini-2.5-flash",
        transport=httpx.MockTransport(handler),
    )
    result = llm.complete_json_with_images(
        "system", "campaign", {"type": "object"}, "visual", [(12.5, str(frame))]
    )
    content = seen["body"]["messages"][1]["content"]
    assert result == {"frames": []}
    assert content[0]["text"] == "campaign"
    assert "12.5 seconds" in content[1]["text"]
    expected = "data:image/jpeg;base64," + base64.b64encode(frame.read_bytes()).decode()
    assert content[2]["image_url"]["url"] == expected


def test_detect_black_intervals_parses_merges_and_clamps_ffmpeg_output(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from clipyyy import vision

    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        return SimpleNamespace(
            stderr=(
                "black_start:0.000 black_end:1.000 black_duration:1.000\n"
                "black_start:0.950 black_end:2.000 black_duration:1.050\n"
                "black_start:9.500 black_end:N/A black_duration:0.500"
            ),
            returncode=0,
        )

    monkeypatch.setattr(vision.subprocess, "run", fake_run)
    intervals = vision.detect_black_intervals(tmp_path / "source.mp4", 10.0)

    assert intervals == [(0.0, 2.0), (9.5, 10.0)]
    assert "blackdetect=d=0.35:pix_th=0.04" in seen["command"]


def test_sample_frames_extracts_evenly_spaced_frames(tmp_path, monkeypatch):
    from clipyyy import vision

    calls = []

    def fake_ffmpeg(args):
        output = tmp_path / "campaign-frames" / args[-1].split("/")[-1]
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"frame")
        calls.append(args)

    monkeypatch.setattr(vision, "run_ffmpeg", fake_ffmpeg)
    frames = sample_frames(tmp_path / "source.mp4", 120.0, tmp_path, limit=4)
    assert len(frames) == 4
    assert [round(item[0], 1) for item in frames] == [15.0, 45.0, 75.0, 105.0]
    assert len(calls) == 4


def test_reference_video_analysis_extracts_visual_style(tmp_path, monkeypatch):
    from clipyyy import vision

    monkeypatch.setattr(
        vision,
        "sample_frames",
        lambda *args, **kwargs: [(2.0, str(tmp_path / "reference.jpg"))],
    )

    class FakeVisionLLM:
        def complete_json_with_images(self, system, user, schema, name, frames):
            assert "visual editing analyst" in system
            assert "recreated with different source footage" in user
            assert name == "campaign_reference_analysis"
            return {
                "frames": [
                    {
                        "timestamp": 2.0,
                        "description": "Close-up product shot with bold centred title",
                        "mood": "energetic",
                        "subjects": "product",
                    }
                ]
            }

    result = vision.analyze_reference_video(
        {"video_path": str(tmp_path / "reference.mp4"), "duration_seconds": 10},
        tmp_path,
        FakeVisionLLM(),
    )
    assert result["frames"][0]["description"].startswith("Close-up product")


def test_text_only_campaign_analysis_keeps_timestamps_without_fabricating_visuals(tmp_path, monkeypatch):
    from clipyyy import vision

    monkeypatch.setattr(
        vision,
        "sample_frames",
        lambda *args, **kwargs: [(3.0, "frame-a.jpg"), (8.0, "frame-b.jpg"), (13.0, "frame-c.jpg")],
    )
    monkeypatch.setattr(vision, "detect_black_intervals", lambda *args: [])

    class TextOnlyLLM:
        pass

    result = vision.analyze_campaign_video(
        {"video_path": "source.mp4", "duration_seconds": 16},
        tmp_path,
        TextOnlyLLM(),
        "Campaign brief",
    )
    assert [frame["timestamp"] for frame in result["frames"]] == [3.0, 8.0, 13.0]
    assert all("Visual content unavailable" in frame["description"] for frame in result["frames"])
    assert all(frame["subjects"] == "not analyzed" for frame in result["frames"])


def test_text_only_analysis_excludes_frames_inside_detected_black_intervals(tmp_path, monkeypatch):
    from clipyyy import vision

    monkeypatch.setattr(
        vision,
        "sample_frames",
        lambda *args, **kwargs: [(3.0, "frame-a.jpg"), (8.0, "frame-b.jpg"), (13.0, "frame-c.jpg")],
    )
    monkeypatch.setattr(vision, "detect_black_intervals", lambda *args: [(5.0, 10.0)])
    monkeypatch.setattr(vision, "detect_scene_changes", lambda *args: [4.0, 7.0, 12.0])

    result = vision.analyze_campaign_video(
        {"video_path": "source.mp4", "duration_seconds": 16},
        tmp_path,
        object(),
        "Campaign brief",
    )

    assert [frame["timestamp"] for frame in result["frames"]] == [4.0, 12.0]
    assert result["black_intervals"] == [(5.0, 10.0)]


def test_text_only_ollama_model_is_not_treated_as_vision_capable():
    from clipyyy.vision import supports_visual_input

    class Provider:
        local = True

    class TextOnlyModel:
        provider = Provider()
        model = "qwen2.5:1.5b"

        def complete_json_with_images(self, *args, **kwargs):
            raise AssertionError("must not send image input to a text-only model")

    assert supports_visual_input(TextOnlyModel()) is False


def test_local_vision_model_is_recognized():
    from clipyyy.vision import supports_visual_input

    class Provider:
        local = True

    class VisionModel:
        provider = Provider()
        model = "qwen2.5vl:3b"

        def complete_json_with_images(self, *args, **kwargs):
            return {}

    assert supports_visual_input(VisionModel()) is True
