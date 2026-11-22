import json

import pytest
from fastapi.testclient import TestClient

from clipyyy import db, pipeline
from clipyyy.api import create_app


@pytest.fixture
def client():
    with TestClient(create_app(start_worker=False)) as c:
        yield c


def test_settings_are_masked_and_updatable(client):
    r = client.put(
        "/api/settings", json={"values": {"openrouter_api_key": "sk-or-1234567890abcd", "llm_model": "a/b"}}
    )
    assert r.status_code == 200
    rows = {s["key"]: s for s in client.get("/api/settings").json()}
    assert rows["openrouter_api_key"]["value"] == "sk-••••abcd"
    assert rows["openrouter_api_key"]["source"] == "app"
    assert rows["llm_model"]["value"] == "a/b"
    # Sending the masked value back must not overwrite the real key
    client.put("/api/settings", json={"values": {"openrouter_api_key": "sk-••••abcd"}})
    assert db.get_setting("openrouter_api_key") == "sk-or-1234567890abcd"
    client.put("/api/settings", json={"values": {"openrouter_api_key": None}})
    assert db.get_setting("openrouter_api_key") is None
    assert client.put("/api/settings", json={"values": {"nope": "x"}}).status_code == 400


def test_run_lifecycle(client):
    r = client.post(
        "/api/runs",
        json={"sources": ["https://youtu.be/abc", " "], "options": {"clip_count": 2, "aspect_ratio": "1:1"}},
    )
    assert r.status_code == 200 and len(r.json()) == 1
    run = r.json()[0]
    assert run["status"] == "queued" and run["options"]["clip_count"] == 2

    detail = client.get(f"/api/runs/{run['id']}").json()
    assert [s["name"] for s in detail["stages"]][:3] == ["download", "transcribe", "select"]
    assert all(s["status"] == "pending" for s in detail["stages"])

    assert client.post(f"/api/runs/{run['id']}/retry").status_code == 409
    db.update_run(run["id"], status="failed")
    assert client.post(f"/api/runs/{run['id']}/retry", json={"from_stage": "bogus"}).status_code == 400
    assert (
        client.post(f"/api/runs/{run['id']}/retry", json={"from_stage": "select"}).json()["status"]
        == "queued"
    )

    assert client.get(f"/api/runs/{run['id']}/download").status_code == 404
    assert client.delete(f"/api/runs/{run['id']}").status_code == 200
    assert client.get(f"/api/runs/{run['id']}").status_code == 404


def test_invalid_options_rejected(client):
    r = client.post("/api/runs", json={"sources": ["x"], "options": {"min_seconds": 50, "max_seconds": 51}})
    assert r.status_code == 422


def test_upload_and_health(client):
    r = client.post("/api/uploads", files={"file": ("talk.mp4", b"data", "video/mp4")})
    assert r.status_code == 200 and r.json()["name"] == "talk.mp4"
    checks = {c["name"]: c for c in client.get("/api/health").json()["checks"]}
    assert checks["llm"]["ok"] is False


def test_buffer_without_key(client):
    assert client.get("/api/buffer/channels").status_code == 400


def test_run_detail_reports_stage_elapsed_time(client):
    run = db.create_run("local.mp4", {})
    db.set_stage(run["id"], "transcribe", "running")
    with db.connect() as conn:
        conn.execute(
            "UPDATE stages SET started_at = ?, finished_at = ? WHERE run_id = ? AND name = ?",
            (
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:01:05+00:00",
                run["id"],
                "transcribe",
            ),
        )

    detail = client.get(f"/api/runs/{run['id']}").json()
    stage = next(item for item in detail["stages"] if item["name"] == "transcribe")
    assert stage["duration_seconds"] == 65.0


def test_campaign_run_accepts_public_campaign_url_without_manual_brief(client):
    response = client.post(
        "/api/runs",
        json={
            "sources": ["local-video.mp4"],
            "options": {
                "campaign_mode": True,
                "campaign_url": "https://campaign.example/details",
            },
        },
    )
    assert response.status_code == 200
    assert response.json()[0]["options"]["campaign_url"] == "https://campaign.example/details"


def test_campaign_music_can_be_attached_to_an_existing_run(client):
    from pathlib import Path

    run = db.create_run(
        "local-video.mp4",
        {"campaign_mode": True, "campaign_music_path": None},
        status="failed",
    )
    response = client.post(
        f"/api/runs/{run['id']}/campaign-music",
        files={"file": ("midnight-sunlight.mp3", b"audio-data", "audio/mpeg")},
    )
    assert response.status_code == 200
    updated = client.get(f"/api/runs/{run['id']}").json()
    music_path = updated["options"]["campaign_music_path"]
    assert music_path.endswith("midnight-sunlight.mp3")
    assert Path(music_path).is_file()


def test_campaign_audio_settings_can_be_saved_and_rerendered(client, monkeypatch):
    run = db.create_run(
        "campaign",
        {
            "campaign_mode": True,
            "campaign_music_path": "campaign-track.mp3",
            "campaign_music_volume": 0.9,
            "campaign_music_fade_in_seconds": 0.4,
            "campaign_music_fade_out_seconds": 0.8,
        },
        status="completed",
    )
    captured = {}

    def fake_rerender(run_id):
        captured["run_id"] = run_id
        captured["options"] = db.get_run(run_id)["options"]
        return {"renders": [{"rank": 1, "status": "ready"}, {"rank": 2, "status": "ready"}]}

    monkeypatch.setattr(pipeline, "rerender_campaign", fake_rerender)
    response = client.put(
        f"/api/runs/{run['id']}/campaign-audio",
        json={"music_volume": 1.25, "fade_in_seconds": 1.2, "fade_out_seconds": 2.5},
    )

    assert response.status_code == 200
    assert response.json() == {"saved": True, "rendered": True, "outputs": 2}
    assert captured["run_id"] == run["id"]
    assert captured["options"]["campaign_music_volume"] == 1.25
    assert captured["options"]["campaign_music_fade_in_seconds"] == 1.2
    assert captured["options"]["campaign_music_fade_out_seconds"] == 2.5


def test_campaign_audio_settings_require_an_attached_music_track(client):
    run = db.create_run("campaign", {"campaign_mode": True, "campaign_music_path": None}, status="completed")
    response = client.put(
        f"/api/runs/{run['id']}/campaign-audio",
        json={"music_volume": 0.9, "fade_in_seconds": 0.4, "fade_out_seconds": 0.8},
    )
    assert response.status_code == 400


def test_campaign_audio_settings_reject_out_of_range_values(client):
    run = db.create_run(
        "campaign", {"campaign_mode": True, "campaign_music_path": "track.mp3"}, status="completed"
    )
    response = client.put(
        f"/api/runs/{run['id']}/campaign-audio",
        json={"music_volume": 2.1, "fade_in_seconds": 0.4, "fade_out_seconds": 0.8},
    )
    assert response.status_code == 422


def test_run_download_archive_is_persisted_under_clipyyy_home(client, tmp_path):
    from clipyyy.config import home

    run = db.create_run("local-video.mp4", {}, status="completed")
    clip_file = tmp_path / "rendered-clip.mp4"
    clip_file.write_bytes(b"fake-video")
    db.replace_clips(
        run["id"],
        [
            {
                "rank": 1,
                "start_seconds": 0,
                "end_seconds": 10,
                "duration_seconds": 10,
                "title": "Test clip",
                "post_title": "Test clip",
                "caption": "A launch worth watching.",
                "hashtags": ["#launch", "#brand"],
                "rationale": "",
                "transcript": "",
                "file_path": str(clip_file),
                "status": "ready",
            }
        ],
    )

    response = client.get(f"/api/runs/{run['id']}/download")
    assert response.status_code == 200
    archives = list((home() / "exports").glob(f"clipyyy-*-{run['id'][:8]}.zip"))
    assert len(archives) == 1
    archive = archives[0]
    import zipfile

    with zipfile.ZipFile(archive) as zf:
        assert "rendered-clip.mp4" in zf.namelist()
        assert "POSTING-COPY.txt" in zf.namelist()
        posting_copy = zf.read("POSTING-COPY.txt").decode("utf-8")
        assert "Test clip" in posting_copy
        assert "A launch worth watching." in posting_copy
        assert "#launch #brand" in posting_copy
        assert "rendered-clip.mp4" in posting_copy


def test_run_detail_exposes_filler_removal_count(client):
    run = db.create_run("local.mp4", {})
    db.replace_clips(
        run["id"],
        [
            {
                "rank": 1,
                "start_seconds": 1.0,
                "end_seconds": 10.0,
                "duration_seconds": 8.0,
                "title": "Test clip",
                "post_title": "Test clip",
                "caption": "A caption",
                "hashtags": [],
                "rationale": "A reason",
                "score": None,
                "transcript": "A transcript",
                "file_path": None,
                "width": 1080,
                "height": 1920,
                "status": "ready",
                "error": None,
            }
        ],
    )
    render_file = pipeline.run_dir(run["id"]) / "work" / "render.json"
    render_file.parent.mkdir(parents=True, exist_ok=True)
    render_file.write_text(
        json.dumps({"renders": [{"rank": 1, "filler_words_removed": 2}]}),
        encoding="utf-8",
    )

    detail = client.get(f"/api/runs/{run['id']}").json()

    assert detail["clips"][0]["filler_words_removed"] == 2


def test_campaign_frame_endpoint_returns_and_caches_source_thumbnail(client, tmp_path, monkeypatch):
    from pathlib import Path

    run = db.create_run("campaign", {"campaign_mode": True}, status="completed")
    source = tmp_path / "campaign-source.mp4"
    source.write_bytes(b"fake-video")
    work_dir = pipeline.run_dir(run["id"]) / "work"
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "download.json").write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "video_path": str(source),
                        "duration_seconds": 12.0,
                        "title": "Campaign source",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    calls = []

    def fake_run_ffmpeg(args):
        calls.append(args)
        Path(args[-1]).write_bytes(b"fake-jpeg")

    monkeypatch.setattr("clipyyy.media.run_ffmpeg", fake_run_ffmpeg)
    url = f"/api/runs/{run['id']}/campaign-frame?source_index=0&timestamp=4.2"

    first = client.get(url)
    second = client.get(url)

    assert first.status_code == 200
    assert first.headers["content-type"] == "image/jpeg"
    assert first.content == b"fake-jpeg"
    assert second.content == b"fake-jpeg"
    assert len(calls) == 1
    assert "scale=480:-2" in calls[0]


def test_campaign_frame_endpoint_rejects_invalid_source_and_timestamp(client, tmp_path):
    run = db.create_run("campaign", {"campaign_mode": True}, status="completed")
    source = tmp_path / "campaign-source.mp4"
    source.write_bytes(b"fake-video")
    work_dir = pipeline.run_dir(run["id"]) / "work"
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "download.json").write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "video_path": str(source),
                        "duration_seconds": 12.0,
                        "title": "Campaign source",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    invalid_source = client.get(f"/api/runs/{run['id']}/campaign-frame?source_index=3&timestamp=4.2")
    invalid_timestamp = client.get(f"/api/runs/{run['id']}/campaign-frame?source_index=0&timestamp=12")

    assert invalid_source.status_code == 404
    assert invalid_timestamp.status_code == 400


def test_campaign_montage_endpoint_accepts_creator_storyboard(client, monkeypatch):
    run = db.create_run("campaign", {"campaign_mode": True}, status="completed")
    captured = {}

    def fake_update(run_id, edits):
        captured["run_id"] = run_id
        captured["edits"] = edits
        return {"renders": [{"rank": 1, "status": "ready"}]}

    monkeypatch.setattr(pipeline, "update_campaign_montage", fake_update)
    response = client.put(
        f"/api/runs/{run['id']}/campaign-montage",
        json={
            "edits": [
                {
                    "rank": 1,
                    "title": "Campaign cut",
                    "shots": [
                        {"source_index": 0, "start_seconds": 0, "end_seconds": 2.5, "reason": "opening"},
                        {"source_index": 0, "start_seconds": 3, "end_seconds": 5.5, "reason": "build"},
                        {"source_index": 1, "start_seconds": 6, "end_seconds": 8.5, "reason": "payoff"},
                    ],
                }
            ]
        },
    )

    assert response.status_code == 200
    assert response.json() == {"saved": True, "rendered": True, "outputs": 1}
    assert captured["run_id"] == run["id"]
    assert captured["edits"][0]["shots"][2]["source_index"] == 1


def test_campaign_montage_endpoint_rejects_too_few_shots(client):
    run = db.create_run("campaign", {"campaign_mode": True}, status="completed")
    response = client.put(
        f"/api/runs/{run['id']}/campaign-montage",
        json={
            "edits": [
                {
                    "rank": 1,
                    "title": "Campaign cut",
                    "shots": [
                        {"source_index": 0, "start_seconds": 0, "end_seconds": 2.5},
                        {"source_index": 0, "start_seconds": 3, "end_seconds": 5.5},
                    ],
                }
            ]
        },
    )

    assert response.status_code == 422


def test_campaign_run_detail_exposes_safe_storyboard_sources(client, monkeypatch, tmp_path):
    run = db.create_run("campaign", {"campaign_mode": True}, status="completed")
    run_root = tmp_path / run["id"]
    work_dir = run_root / "work"
    work_dir.mkdir(parents=True)
    monkeypatch.setattr(pipeline, "run_dir", lambda run_id: run_root)
    edit = {
        "rank": 1,
        "title": "Campaign cut",
        "shots": [
            {"source_index": 0, "start_seconds": 0, "end_seconds": 2.5, "reason": "opening"},
            {"source_index": 0, "start_seconds": 3, "end_seconds": 5.5, "reason": "build"},
            {"source_index": 0, "start_seconds": 6, "end_seconds": 8.5, "reason": "payoff"},
        ],
    }
    (work_dir / "download.json").write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "title": "Summer campaign footage",
                        "duration_seconds": 40,
                        "video_path": "private/local/path.mp4",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (work_dir / "select.json").write_text(
        json.dumps(
            {
                "campaign_plan": {"campaign_name": "Summer"},
                "campaign_edits": [edit],
                "campaign_original_edits": [edit],
                "campaign_lyric_cues": [
                    {"text": "We rise together", "start_seconds": 1.2, "end_seconds": 2.8}
                ],
            }
        ),
        encoding="utf-8",
    )

    detail = client.get(f"/api/runs/{run['id']}").json()

    assert detail["campaign_edits"] == [edit]
    assert detail["campaign_original_edits"] == [edit]
    assert detail["campaign_lyric_cues"] == [
        {"text": "We rise together", "start_seconds": 1.2, "end_seconds": 2.8}
    ]
    assert detail["campaign_sources"] == [
        {"index": 0, "title": "Summer campaign footage", "duration_seconds": 40.0}
    ]
    assert "video_path" not in detail["campaign_sources"][0]
