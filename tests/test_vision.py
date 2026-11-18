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
        PROVIDERS["gemini"], "test-key", "gemini-2.5-flash",
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


def test_sample_frames_extracts_evenly_spaced_frames(tmp_path, monkeypatch):
    from clipyyy import vision

    calls = []

    def fake_ffmpeg(args):
        output = tmp_path / "frames" / args[-1].split("/")[-1]
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"frame")
        calls.append(args)

    monkeypatch.setattr(vision, "run_ffmpeg", fake_ffmpeg)
    frames = sample_frames(tmp_path / "source.mp4", 120.0, tmp_path, limit=4)
    assert len(frames) == 4
    assert [round(item[0], 1) for item in frames] == [15.0, 45.0, 75.0, 105.0]
    assert len(calls) == 4
