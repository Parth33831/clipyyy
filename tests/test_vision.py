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


def test_scene_aware_sampling_prioritizes_cut_coverage_and_fills_with_uniform_frames(tmp_path, monkeypatch):
    from clipyyy import vision

    calls = []

    def fake_ffmpeg(args):
        output = tmp_path / "campaign-frames" / args[-1].split("/")[-1]
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"frame")
        calls.append(args)

    monkeypatch.setattr(vision, "detect_scene_changes", lambda *args, **kwargs: [10, 20, 30, 40, 50, 60])
    monkeypatch.setattr(vision, "run_ffmpeg", fake_ffmpeg)

    frames = vision.sample_scene_aware_frames(tmp_path / "source.mp4", 80, tmp_path, limit=6)

    timestamps = [timestamp for timestamp, _ in frames]
    assert len(frames) == 6
    assert timestamps == sorted(timestamps)
    assert any(abs(timestamp - 10.35) < 0.01 for timestamp in timestamps)
    assert any(abs(timestamp - 60.35) < 0.01 for timestamp in timestamps)
    assert len(calls) == 6


def test_scene_aware_sampling_falls_back_to_uniform_frames_without_detected_cuts(tmp_path, monkeypatch):
    from clipyyy import vision

    expected = [(5.0, "frame-a.jpg"), (15.0, "frame-b.jpg")]
    monkeypatch.setattr(vision, "detect_scene_changes", lambda *args, **kwargs: [])
    monkeypatch.setattr(vision, "sample_frames", lambda *args, **kwargs: expected)

    assert vision.sample_scene_aware_frames(tmp_path / "source.mp4", 20, tmp_path, limit=4) == expected


def test_campaign_vision_analysis_uses_scene_aware_sampling_for_vision_models(tmp_path, monkeypatch):
    from clipyyy import vision

    sampled = [(4.0, "scene-a.jpg"), (9.0, "scene-b.jpg")]
    monkeypatch.setattr(vision, "sample_scene_aware_frames", lambda *args, **kwargs: sampled)

    class VisionLLM:
        provider = None

        def complete_json_with_images(self, system, user, schema, name, frames):
            assert frames == sampled
            return {
                "frames": [
                    {
                        "timestamp": 4.0,
                        "description": "Wide shot",
                        "mood": "calm",
                        "subjects": "person",
                    },
                    {
                        "timestamp": 9.0,
                        "description": "Close-up",
                        "mood": "focused",
                        "subjects": "product",
                    },
                ]
            }

    result = vision.analyze_campaign_video(
        {"video_path": str(tmp_path / "source.mp4"), "duration_seconds": 12},
        tmp_path,
        VisionLLM(),
        "Campaign brief",
    )
    assert [frame["timestamp"] for frame in result["frames"]] == [4.0, 9.0]


def test_campaign_visual_analysis_returns_grounded_structured_scene_attributes(tmp_path, monkeypatch):
    from clipyyy import vision

    monkeypatch.setattr(
        vision,
        "sample_scene_aware_frames",
        lambda *args, **kwargs: [(4.0, "frame-a.jpg")],
    )

    class VisionLLM:
        provider = None

        def complete_json_with_images(self, system, user, schema, name, frames):
            assert "single still image" in system
            properties = schema["properties"]["frames"]["items"]["properties"]
            assert {"shot_scale", "visible_action", "visible_text", "confidence"} <= set(properties)
            assert {
                "shot_scale",
                "visible_action",
                "visible_text",
                "confidence",
            } <= set(schema["properties"]["frames"]["items"]["required"])
            return {
                "frames": [
                    {
                        "timestamp": 4,
                        "description": "Close-up of a person holding a phone",
                        "mood": "focused",
                        "subjects": "person, phone",
                        "shot_scale": "close-up",
                        "visible_action": "person holding phone",
                        "visible_text": "unknown",
                        "confidence": 0.92,
                    },
                    {
                        "timestamp": "bad",
                        "description": "invalid timestamp",
                    },
                ]
            }

    result = vision.analyze_campaign_video(
        {"video_path": str(tmp_path / "source.mp4"), "duration_seconds": 12},
        tmp_path,
        VisionLLM(),
        "Show the product in use",
    )

    assert len(result["frames"]) == 1
    frame = result["frames"][0]
    assert frame["shot_scale"] == "close-up"
    assert frame["visible_action"] == "person holding phone"
    assert frame["visible_text"] == "unknown"
    assert frame["confidence"] == 0.92


def test_visual_attribute_normalization_is_backward_compatible_and_bounded():
    from clipyyy.vision import _normalize_frame_observations

    frames = _normalize_frame_observations(
        {
            "frames": [
                {
                    "timestamp": 1,
                    "description": "legacy observation",
                    "mood": "calm",
                    "subjects": "person",
                    "confidence": 4.5,
                }
            ]
        }
    )

    assert frames[0]["description"] == "legacy observation"
    assert frames[0]["shot_scale"] == "unknown"
    assert frames[0]["visible_action"] == "unknown"
    assert frames[0]["visible_text"] == "unknown"
    assert frames[0]["confidence"] == 1.0


def test_montage_planner_uses_structured_visual_attributes_as_evidence():
    from clipyyy.campaign import build_montage_plan

    class CapturingLLM:
        user = ""
        system = ""

        def complete_json(self, system, user, schema, name):
            self.system = system
            self.user = user
            return {
                "edits": [
                    {
                        "title": "Product story",
                        "shots": [
                            {
                                "source_index": 0,
                                "start_seconds": 1,
                                "end_seconds": 3,
                                "reason": "context",
                            },
                            {
                                "source_index": 0,
                                "start_seconds": 4,
                                "end_seconds": 6,
                                "reason": "detail",
                            },
                            {
                                "source_index": 0,
                                "start_seconds": 7,
                                "end_seconds": 9,
                                "reason": "payoff",
                            },
                        ],
                    }
                ]
            }

    llm = CapturingLLM()
    source = {"title": "Product footage", "duration_seconds": 12}
    analysis = {
        "frames": [
            {
                "timestamp": 1,
                "description": "Person entering room",
                "mood": "curious",
                "subjects": "person",
                "shot_scale": "wide",
                "visible_action": "person entering room",
                "visible_text": "none",
                "confidence": 0.95,
            },
            {
                "timestamp": 5,
                "description": "Close-up of product",
                "mood": "focused",
                "subjects": "product",
                "shot_scale": "detail",
                "visible_action": "hand holding product",
                "visible_text": "Brand name",
                "confidence": 0.88,
            },
            {
                "timestamp": 8,
                "description": "Person smiling",
                "mood": "happy",
                "subjects": "person",
                "shot_scale": "close-up",
                "visible_action": "smiling",
                "visible_text": "none",
                "confidence": 0.9,
            },
        ]
    }

    edits = build_montage_plan(llm, "Show the product in use", {}, [source], [analysis], 1, 6)

    assert len(edits) == 1
    assert "shot_scale" in llm.system
    assert "visible_action" in llm.system
    assert "Brand name" in llm.user
    assert "0.88" in llm.user
