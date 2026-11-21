import json
from pathlib import Path

from clipyyy import db, pipeline


def test_failed_run_resumes_from_failed_stage(monkeypatch):
    calls = []
    fail = {"plan": True}

    def make(name):
        def fn(ctx):
            calls.append(name)
            if fail.get(name):
                raise RuntimeError("kaboom")
            return {"stage": name}

        return fn

    monkeypatch.setattr(
        pipeline, "STAGES", [(n, n, make(n)) for n in ("download", "transcribe", "plan", "render")]
    )
    monkeypatch.setattr(pipeline, "STAGE_NAMES", ["download", "transcribe", "plan", "render"])
    run = db.create_run("file.mp4", pipeline.ClipOptions().model_dump(), status="running")

    pipeline.execute(run)
    failed = db.get_run(run["id"])
    assert failed["status"] == "failed" and failed["error"] == "plan: kaboom"
    assert calls == ["download", "transcribe", "plan"]

    fail["plan"] = False
    pipeline.retry(run["id"])
    assert db.claim_next_run()["id"] == run["id"]
    pipeline.execute(db.get_run(run["id"]))
    assert calls[3:] == ["plan", "render"]
    assert db.get_run(run["id"])["status"] == "completed"
    assert {s["name"]: s["status"] for s in db.list_stages(run["id"])}["render"] == "done"

    pipeline.retry(run["id"], from_stage="plan")
    db.update_run(run["id"], status="running")
    pipeline.execute(db.get_run(run["id"]))
    assert calls[5:] == ["plan", "render"]


def test_options_validation():
    import pytest

    with pytest.raises(ValueError):
        pipeline.ClipOptions(min_seconds=50, max_seconds=52)
    assert pipeline.ClipOptions().aspect_ratio == "9:16"


def test_requeue_only_touches_runs_of_dead_processes():
    import os

    mine = db.create_run("a.mp4", {}, status="running")  # claimed by this (live) process
    orphan = db.create_run("b.mp4", {}, status="running")
    db.update_run(orphan["id"], claimed_by=2**22 + 12345)  # no such pid
    db.update_run(mine["id"], claimed_by=os.getppid())
    db.requeue_interrupted_runs()
    assert db.get_run(mine["id"])["status"] == "running"
    assert db.get_run(orphan["id"])["status"] == "queued"


def test_campaign_selection_uses_local_ollama_without_cloud_fallback(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from clipyyy import campaign, llm, vision

    local_llm = SimpleNamespace(provider=SimpleNamespace(local=True), model="qwen2.5vl:3b")
    monkeypatch.setattr(llm, "get_llm", lambda model=None: local_llm)
    monkeypatch.setattr(pipeline, "get_setting", lambda key: "")
    monkeypatch.setattr(
        campaign,
        "parse_campaign_brief",
        lambda client, brief: {
            "campaign_name": "Local campaign",
            "output_count": 1,
            "target_duration_seconds": 8,
        },
    )
    monkeypatch.setattr(
        vision,
        "analyze_campaign_video",
        lambda *args: {
            "frames": [
                {"timestamp": 1.0, "description": "opening scene", "mood": "calm", "subjects": "person"},
                {"timestamp": 5.0, "description": "action scene", "mood": "energetic", "subjects": "person"},
                {"timestamp": 9.0, "description": "closing scene", "mood": "hopeful", "subjects": "person"},
            ]
        },
    )
    monkeypatch.setattr(
        campaign,
        "build_montage_plan",
        lambda *args, **kwargs: [
            {
                "rank": 1,
                "title": "Local edit",
                "shots": [{"source_index": 0, "start_seconds": 1.0, "end_seconds": 3.0}],
            }
        ],
    )

    source = {
        "title": "Source video",
        "duration_seconds": 12.0,
        "video_path": str(tmp_path / "source.mp4"),
    }
    ctx = pipeline.Context(
        run_id="local-campaign-test",
        source="source.mp4",
        options=pipeline.ClipOptions(
            campaign_mode=True,
            campaign_brief="Make a hopeful campaign edit",
        ).model_dump(),
        work_dir=tmp_path,
        out_dir=tmp_path / "clips",
        state={"download": {"title": "Source video", "sources": [source]}},
    )

    result = pipeline.stage_select(ctx)

    assert result["campaign_plan"]["campaign_name"] == "Local campaign"
    assert result["clips"][0]["title"] == "Local edit"
    assert result["clips"][0]["campaign_shots"][0]["source_index"] == 0


def test_campaign_options_preserve_creative_settings():
    options = pipeline.ClipOptions(
        campaign_mode=True,
        campaign_lyrics_style="karaoke",
        campaign_hook_text="Stay until the end",
        include_campaign_hook=True,
    ).model_dump()
    assert options["campaign_lyrics_style"] == "karaoke"
    assert options["campaign_hook_text"] == "Stay until the end"
    assert options["include_campaign_hook"] is True


def test_campaign_transcribe_skips_source_videos_for_manual_dialogue():
    ctx = pipeline.Context(
        run_id="campaign-manual-dialogue-test",
        source="[]",
        options=pipeline.ClipOptions(campaign_mode=True).model_dump(),
        work_dir=Path("unused-work"),
        out_dir=Path("unused-out"),
        state={"download": {"sources": [{"video_path": "unused.mp4"}]}},
    )

    result = pipeline.stage_transcribe(ctx)

    assert result == {"language": "campaign", "sources": []}


def test_filler_removal_option_is_off_by_default_and_preserved():
    options = pipeline.ClipOptions().model_dump()
    assert options["remove_filler_words"] is False
    assert pipeline.ClipOptions(remove_filler_words=True).model_dump()["remove_filler_words"] is True


def _campaign_edit_fixture(tmp_path, run_id):
    run_root = tmp_path / run_id
    work_dir = run_root / "work"
    work_dir.mkdir(parents=True)
    shots = [
        {"source_index": 0, "start_seconds": 0.0, "end_seconds": 2.5, "reason": "opening"},
        {"source_index": 0, "start_seconds": 3.0, "end_seconds": 5.5, "reason": "build"},
        {"source_index": 0, "start_seconds": 6.0, "end_seconds": 8.5, "reason": "payoff"},
    ]
    source_data = {
        "sources": [
            {
                "title": "Campaign footage",
                "duration_seconds": 40.0,
                "video_path": str(tmp_path / "source.mp4"),
            }
        ]
    }
    edit = {"rank": 1, "title": "Campaign cut", "shots": shots}
    selection = {
        "campaign_plan": {"target_duration_seconds": 10.0},
        "campaign_edits": [edit],
        "campaign_original_edits": [edit],
        "clips": [
            {
                "rank": 1,
                "start_seconds": 0.0,
                "end_seconds": 7.5,
                "duration_seconds": 7.5,
                "campaign_shots": shots,
            }
        ],
    }
    (work_dir / "download.json").write_text(json.dumps(source_data), encoding="utf-8")
    (work_dir / "select.json").write_text(json.dumps(selection), encoding="utf-8")
    return run_root, selection, edit


def test_campaign_shot_edits_rebuild_cached_montage_and_keep_ai_reset(tmp_path, monkeypatch):
    run = db.create_run("campaign", {"campaign_mode": True}, status="completed")
    run_root, original_selection, original_edit = _campaign_edit_fixture(tmp_path, run["id"])
    monkeypatch.setattr(pipeline, "run_dir", lambda run_id: run_root)
    calls = []

    def fake_render(source, selection, work_dir, out_dir, options):
        calls.append((selection, options["reuse_campaign_montage"]))
        return {
            "renders": [
                {
                    "rank": 1,
                    "status": "ready",
                    "file_path": str(tmp_path / "campaign.mp4"),
                    "width": 1080,
                    "height": 1920,
                    "duration_seconds": 10.0,
                }
            ]
        }

    from clipyyy import render

    monkeypatch.setattr(render, "render_campaign_montages", fake_render)
    edited = {
        "rank": 1,
        "title": "Campaign cut",
        "shots": [
            original_edit["shots"][1],
            original_edit["shots"][0],
            original_edit["shots"][2],
        ],
    }

    result = pipeline.update_campaign_montage(run["id"], [edited])

    saved = json.loads((run_root / "work" / "select.json").read_text(encoding="utf-8"))
    assert result["renders"][0]["status"] == "ready"
    assert [shot["start_seconds"] for shot in saved["campaign_edits"][0]["shots"]] == [3.0, 0.0, 6.0]
    assert saved["campaign_original_edits"] == original_selection["campaign_original_edits"]
    assert calls[0][1] is False
    assert db.get_run(run["id"])["status"] == "completed"

    pipeline.rerender_campaign(run["id"])
    assert calls[1][1] is True


def test_campaign_shot_edit_rejects_invalid_ranges_without_overwriting_plan(tmp_path, monkeypatch):
    run = db.create_run("campaign", {"campaign_mode": True}, status="completed")
    run_root, original_selection, original_edit = _campaign_edit_fixture(tmp_path, run["id"])
    monkeypatch.setattr(pipeline, "run_dir", lambda run_id: run_root)
    invalid = {
        "rank": 1,
        "title": "Campaign cut",
        "shots": [
            {**original_edit["shots"][0], "source_index": 4},
            original_edit["shots"][1],
            original_edit["shots"][2],
        ],
    }

    import pytest

    with pytest.raises(ValueError, match="unknown source"):
        pipeline.update_campaign_montage(run["id"], [invalid])

    saved = json.loads((run_root / "work" / "select.json").read_text(encoding="utf-8"))
    assert saved["campaign_edits"] == original_selection["campaign_edits"]
    assert db.get_run(run["id"])["status"] == "completed"


def test_campaign_shot_edit_requires_three_valid_shots(tmp_path, monkeypatch):
    run = db.create_run("campaign", {"campaign_mode": True}, status="completed")
    run_root, _, original_edit = _campaign_edit_fixture(tmp_path, run["id"])
    monkeypatch.setattr(pipeline, "run_dir", lambda run_id: run_root)
    invalid = {"rank": 1, "title": "Campaign cut", "shots": original_edit["shots"][:2]}

    import pytest

    with pytest.raises(ValueError, match="at least 3 shots"):
        pipeline.update_campaign_montage(run["id"], [invalid])

def test_campaign_camera_motion_is_enabled_by_default_and_can_be_disabled():
    assert pipeline.ClipOptions(campaign_mode=True).campaign_camera_motion is True
    assert pipeline.ClipOptions(campaign_mode=True, campaign_camera_motion=False).campaign_camera_motion is False
