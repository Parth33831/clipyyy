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
