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
