from clipyyy.campaign import CampaignPlan, format_campaign_plan, local_fallback_plan


def test_campaign_plan_keeps_unknowns_unknown():
    plan = CampaignPlan(campaign_name="Summer launch", platform=["TikTok"]).model_dump()
    assert plan["campaign_name"] == "Summer launch"
    assert plan["platform"] == ["TikTok"]
    assert plan["audio_mode"] is None
    assert plan["official_platform_sound_required"] is None
    assert plan["post_upload_actions"] == []


def test_campaign_plan_separates_video_and_post_upload_requirements():
    plan = CampaignPlan(
        mandatory_content=["Show product logo"],
        post_upload_actions=["Comment the campaign name"],
        performance_eligibility=["At least 2,000 views"],
    ).model_dump()
    formatted = format_campaign_plan(plan)
    assert "Mandatory: Show product logo" in formatted
    assert "Post-upload actions (manual): Comment the campaign name" in formatted
    assert "Post-publication eligibility: At least 2,000 views" in formatted


def test_local_fallback_does_not_guess_campaign_category():
    plan = local_fallback_plan("A mysterious campaign brief")
    assert plan["content_type"] is None
    assert plan["subject_or_theme"] is None
    assert plan["unresolved_questions"]


class FakeMontageLLM:
    def complete_json(self, system, user, schema, name):
        return {
            "edits": [
                {
                    "title": "Emotional campaign cut",
                    "shots": [
                        {"source_index": 0, "start_seconds": 2, "end_seconds": 5, "reason": "opening"},
                        {"source_index": 1, "start_seconds": 8, "end_seconds": 12, "reason": "build"},
                        {
                            "source_index": 0,
                            "start_seconds": 999,
                            "end_seconds": 1005,
                            "reason": "clamped out",
                        },
                        {"source_index": 1, "start_seconds": 15, "end_seconds": 19, "reason": "payoff"},
                    ],
                }
            ]
        }


def test_montage_plan_uses_multiple_sources_and_clamps_timestamps():
    from clipyyy.campaign import build_montage_plan

    sources = [
        {"title": "A", "duration_seconds": 20},
        {"title": "B", "duration_seconds": 30},
    ]
    analyses = [
        {"frames": [{"timestamp": 3, "description": "sunset", "mood": "calm", "subjects": "sky"}]},
        {
            "frames": [
                {"timestamp": 9, "description": "runner", "mood": "hopeful", "subjects": "person"},
                {"timestamp": 17, "description": "finish", "mood": "joy", "subjects": "runner"},
            ]
        },
    ]
    plan = build_montage_plan(FakeMontageLLM(), "Hopeful sports campaign", {}, sources, analyses, 1, 12)
    assert len(plan) == 1
    assert [shot["source_index"] for shot in plan[0]["shots"]] == [0, 1, 1]
    assert all(
        shot["end_seconds"] <= sources[shot["source_index"]]["duration_seconds"] for shot in plan[0]["shots"]
    )


def test_campaign_lyrics_are_timed_and_written(tmp_path):
    from clipyyy.render import write_campaign_lyrics

    path = write_campaign_lyrics(["First line", "Second line"], 10, tmp_path / "lyrics.ass", 1080, 1920)
    text = path.read_text(encoding="utf-8")
    assert "First line" in text
    assert "Second line" in text
    assert "Dialogue:" in text


def test_montage_planner_uses_reference_video_style_without_copying_shots():
    from clipyyy.campaign import build_montage_plan

    class CapturingLLM:
        user = ""

        def complete_json(self, system, user, schema, name):
            self.user = user
            return {
                "edits": [
                    {
                        "title": "Campaign cut",
                        "shots": [
                            {"source_index": 0, "start_seconds": 1, "end_seconds": 3, "reason": "hook"},
                            {"source_index": 0, "start_seconds": 4, "end_seconds": 6, "reason": "build"},
                            {"source_index": 0, "start_seconds": 7, "end_seconds": 9, "reason": "payoff"},
                        ],
                    }
                ]
            }

    llm = CapturingLLM()
    source = {"title": "My footage", "duration_seconds": 12}
    analysis = {
        "frames": [
            {"timestamp": 1, "description": "product", "mood": "bright", "subjects": "item"},
            {"timestamp": 5, "description": "person", "mood": "happy", "subjects": "person"},
            {"timestamp": 8, "description": "logo", "mood": "bold", "subjects": "logo"},
        ]
    }
    reference = {
        "title": "Reference example",
        "frames": [
            {
                "timestamp": 2,
                "description": "Fast close-up cuts with centred kinetic typography",
                "mood": "energetic",
                "subjects": "product",
            }
        ],
    }
    edits = build_montage_plan(
        llm,
        "Product campaign",
        {},
        [source],
        [analysis],
        1,
        6,
        reference_analyses=[reference],
    )
    assert len(edits) == 1
    assert "centred kinetic typography" in llm.user
    assert "never copy reference footage" in llm.user


def test_campaign_brief_falls_back_when_local_model_cannot_return_json():
    from clipyyy.campaign import parse_campaign_brief

    class BrokenLocalLLM:
        def complete_json(self, *args, **kwargs):
            raise RuntimeError("local model returned invalid JSON")

    brief = "Show the product in use. Use the supplied campaign music."
    plan = parse_campaign_brief(BrokenLocalLLM(), brief)
    assert plan["campaign_name"] is None
    assert plan["unresolved_questions"]
    assert "original brief remains the source of truth" in plan["unresolved_questions"][-1]


def test_text_only_campaign_builds_timestamp_spread_without_visual_claims():
    from clipyyy.campaign import build_montage_plan

    class TextOnlyModel:
        def complete_json(self, *args, **kwargs):
            raise AssertionError("text-only fallback must not infer unseen visuals")

    sources = [
        {"title": "A", "duration_seconds": 240},
        {"title": "B", "duration_seconds": 242},
    ]
    unavailable = {
        "frames": [
            {
                "timestamp": 10,
                "description": ("Visual content unavailable: installed model is text-only."),
            }
        ]
    }
    edits = build_montage_plan(
        TextOnlyModel(),
        "Campaign brief",
        {},
        sources,
        [unavailable, unavailable],
        2,
        30,
    )
    assert len(edits) == 2
    assert all(len(edit["shots"]) >= 3 for edit in edits)
    assert all(
        shot["reason"].startswith("Distinct timestamp sample") for edit in edits for shot in edit["shots"]
    )


def test_text_only_campaign_outputs_use_distinct_time_ranges():
    from clipyyy.campaign import _build_text_only_montage

    sources = [
        {"duration_seconds": 482.0},
        {"duration_seconds": 556.0},
    ]
    edits = _build_text_only_montage(sources, output_count=4, target_seconds=35.0)
    ranges = [(shot["source_index"], shot["start_seconds"]) for edit in edits for shot in edit["shots"]]
    assert len(edits) == 4
    assert len(ranges) == len(set(ranges))


def test_campaign_montage_duration_normalization_pads_or_trims(tmp_path, monkeypatch):
    from clipyyy import render

    calls = []

    def fake_run_ffmpeg(args):
        calls.append(args)

    monkeypatch.setattr(render, "run_ffmpeg", fake_run_ffmpeg)
    source = tmp_path / "source.mp4"
    padded = tmp_path / "padded.mp4"
    trimmed = tmp_path / "trimmed.mp4"

    render._normalize_montage_duration(source, padded, 14.2, 15.0)
    render._normalize_montage_duration(source, trimmed, 15.4, 15.0)

    padded_filter = calls[0][calls[0].index("-vf") + 1]
    trimmed_filter = calls[1][calls[1].index("-vf") + 1]
    assert "tpad=stop_mode=clone:stop_duration=0.800" in padded_filter
    assert "trim=duration=15.000" in padded_filter
    assert "tpad=stop_mode=clone:stop_duration=0.000" in trimmed_filter
    assert "trim=duration=15.000" in trimmed_filter



def test_text_only_montage_uses_detected_scene_boundaries():
    from clipyyy.campaign import _build_text_only_montage

    source = {"duration_seconds": 180.0}
    analysis = {
        "frames": [
            {
                "timestamp": float(timestamp),
                "description": "Visual content unavailable: installed model is text-only.",
            }
            for timestamp in range(5, 170, 4)
        ]
    }
    edits = _build_text_only_montage([source], 1, 20, [analysis])
    assert len(edits) == 1
    assert len(edits[0]["shots"]) >= 5
    scene_times = {float(timestamp) for timestamp in range(5, 170, 4)}
    assert all(
        any(abs(shot["start_seconds"] - (timestamp + 0.06)) < 0.01 for timestamp in scene_times)
        or shot["start_seconds"] < 1.0
        for shot in edits[0]["shots"]
    )
    assert all("FFmpeg-detected scene change" in shot["reason"] for shot in edits[0]["shots"])


def test_detect_scene_changes_extracts_and_limits_ffmpeg_timestamps(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from clipyyy import vision

    stderr = "\n".join(f"[Parsed_showinfo] n:{i} pts_time:{i * 2}.000" for i in range(1, 15))
    monkeypatch.setattr(
        vision.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stderr=stderr, returncode=0),
    )
    timestamps = vision.detect_scene_changes(tmp_path / "source.mp4", 40, limit=5)
    assert len(timestamps) == 5
    assert timestamps[0] == 2.0
    assert timestamps[-1] == 28.0
