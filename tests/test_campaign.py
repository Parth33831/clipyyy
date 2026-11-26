import pytest

from clipyyy.campaign import (
    CampaignPlan,
    format_campaign_plan,
    generate_ai_edit_proposal,
    local_fallback_plan,
)


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
    assert all("not analysed" in shot["reason"].lower() for edit in edits for shot in edit["shots"])


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


def test_text_only_montage_never_selects_shots_overlapping_black_sections():
    from clipyyy.campaign import _build_text_only_montage

    sources = [{"duration_seconds": 120.0}]
    analyses = [
        {
            "frames": [
                {"timestamp": float(timestamp), "description": "Visual content unavailable"}
                for timestamp in range(5, 116, 5)
            ],
            "black_intervals": [[0.0, 22.0], [48.0, 70.0]],
        }
    ]

    edits = _build_text_only_montage(sources, output_count=1, target_seconds=15.0, analyses=analyses)

    assert len(edits[0]["shots"]) >= 3
    for shot in edits[0]["shots"]:
        start, end = shot["start_seconds"], shot["end_seconds"]
        assert not (start < 22.0 and end > 0.0)
        assert not (start < 70.0 and end > 48.0)


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


def test_montage_planner_builds_brief_led_story():
    from clipyyy.campaign import build_montage_plan

    class CapturingLLM:
        system = ""
        user = ""

        def complete_json(self, system, user, schema, name):
            self.system = system
            self.user = user
            return {
                "edits": [
                    {
                        "title": "A clear campaign story",
                        "shots": [
                            {"source_index": 0, "start_seconds": 1, "end_seconds": 3, "reason": "Opening"},
                            {"source_index": 0, "start_seconds": 4, "end_seconds": 6, "reason": "Build"},
                            {"source_index": 0, "start_seconds": 7, "end_seconds": 9, "reason": "Payoff"},
                        ],
                    }
                ]
            }

    llm = CapturingLLM()
    source = {"title": "Campaign footage", "duration_seconds": 12}
    analysis = {
        "frames": [
            {
                "timestamp": 1,
                "description": "Person notices a problem",
                "mood": "curious",
                "subjects": "person",
            },
            {
                "timestamp": 5,
                "description": "Person demonstrates a solution",
                "mood": "focused",
                "subjects": "person, product",
            },
            {
                "timestamp": 8,
                "description": "Person smiles while using product",
                "mood": "hopeful",
                "subjects": "person, product",
            },
        ]
    }

    edits = build_montage_plan(
        llm,
        "Show how this product makes daily work easier. Do not make unsupported performance claims.",
        {"mandatory_content": ["Show the product in use"]},
        [source],
        [analysis],
        1,
        6,
    )

    assert len(edits) == 1
    assert "visual storyteller" in llm.system
    assert "omit or adapt any beat" in llm.system
    assert "creator footage as the narrative backbone" in llm.system
    assert "story function" in llm.user
    assert "random" in llm.user
    assert "Do not force a CTA" in llm.user


def test_montage_planner_uses_detected_music_structure_without_overriding_story():
    from clipyyy.campaign import build_montage_plan

    class MusicAwareLLM:
        user = ""

        def complete_json(self, system, user, schema, name):
            self.user = user
            return {
                "edits": [
                    {
                        "title": "Music-led campaign",
                        "shots": [
                            {"source_index": 0, "start_seconds": 1, "end_seconds": 3, "reason": "opening"},
                            {"source_index": 0, "start_seconds": 4, "end_seconds": 6, "reason": "build"},
                            {"source_index": 0, "start_seconds": 7, "end_seconds": 9, "reason": "payoff"},
                        ],
                    }
                ]
            }

    llm = MusicAwareLLM()
    source = {"title": "Campaign footage", "duration_seconds": 12}
    analysis = {
        "frames": [
            {"timestamp": 1, "description": "Quiet preparation"},
            {"timestamp": 5, "description": "Action builds"},
            {"timestamp": 8, "description": "Strong product reveal"},
        ]
    }
    music = {
        "bpm": 120,
        "selected_section": "4.0–10.0s",
        "beat_interval_seconds": 0.5,
        "beat_times": [4.5, 5.0, 5.5, 6.0, 7.0, 8.0],
        "beat_strengths": [0.2, 0.3, 0.4, 0.5, 0.9, 1.0],
        "energy_sections": [
            {"start_seconds": 4.0, "end_seconds": 6.0, "level": "low", "average_energy": 0.2},
            {"start_seconds": 6.0, "end_seconds": 10.0, "level": "high", "average_energy": 0.9},
        ],
    }

    edits = build_montage_plan(
        llm,
        "Show the campaign story",
        {},
        [source],
        [analysis],
        1,
        6,
        music_analysis=music,
    )

    assert len(edits) == 1
    assert "MUSICAL STRUCTURE" in llm.user
    assert "estimated_bpm" in llm.user
    assert "strong_transients_seconds" in llm.user
    assert "reserve the strongest relevant footage" in llm.user
    assert "Do not sacrifice campaign relevance" in llm.user


def test_montage_planner_remains_compatible_without_music_analysis():
    from clipyyy.campaign import build_montage_plan

    llm = FakeMontageLLM()
    sources = [
        {"title": "Footage A", "duration_seconds": 20},
        {"title": "Footage B", "duration_seconds": 20},
    ]
    analysis = {
        "frames": [
            {"timestamp": 1, "description": "opening"},
            {"timestamp": 8, "description": "build"},
            {"timestamp": 15, "description": "payoff"},
        ]
    }
    edits = build_montage_plan(llm, "Campaign", {}, sources, [analysis, analysis], 1, 6)
    assert len(edits) == 1


def test_montage_planner_uses_creator_supplied_lyrics_as_truthful_story_cues():
    from clipyyy.campaign import build_montage_plan

    class LyricAwareLLM:
        user = ""

        def complete_json(self, system, user, schema, name):
            self.user = user
            return {
                "edits": [
                    {
                        "title": "Lyric-aware story",
                        "shots": [
                            {
                                "source_index": 0,
                                "start_seconds": 1,
                                "end_seconds": 3,
                                "reason": "Opening",
                            },
                            {
                                "source_index": 0,
                                "start_seconds": 4,
                                "end_seconds": 6,
                                "reason": "Build",
                            },
                            {
                                "source_index": 0,
                                "start_seconds": 7,
                                "end_seconds": 9,
                                "reason": "Payoff",
                            },
                        ],
                    }
                ]
            }

    llm = LyricAwareLLM()
    source = {"title": "Campaign footage", "duration_seconds": 12}
    analysis = {
        "frames": [
            {"timestamp": 1, "description": "A person looks uncertain"},
            {"timestamp": 5, "description": "A person starts working with a device"},
            {"timestamp": 8, "description": "A person celebrates with friends"},
        ]
    }

    edits = build_montage_plan(
        llm,
        "Show a person overcoming a challenge.",
        {},
        [source],
        [analysis],
        1,
        6,
        campaign_lyrics="When the lights go down\nWe rise together",
    )

    assert len(edits) == 1
    assert "CREATOR-SUPPLIED CAMPAIGN LYRICS" in llm.user
    assert "We rise together" in llm.user
    assert "no word timestamps supplied" in llm.user
    assert "do not assume the lyric is sung at a particular timestamp" in llm.user


def test_montage_planner_omits_lyric_guidance_when_no_lyrics_are_supplied():
    from clipyyy.campaign import build_montage_plan

    class NoLyricsLLM:
        user = ""

        def complete_json(self, system, user, schema, name):
            self.user = user
            return {
                "edits": [
                    {
                        "title": "Campaign story",
                        "shots": [
                            {
                                "source_index": 0,
                                "start_seconds": 1,
                                "end_seconds": 3,
                                "reason": "Opening",
                            },
                            {
                                "source_index": 0,
                                "start_seconds": 4,
                                "end_seconds": 6,
                                "reason": "Build",
                            },
                            {
                                "source_index": 0,
                                "start_seconds": 7,
                                "end_seconds": 9,
                                "reason": "Payoff",
                            },
                        ],
                    }
                ]
            }

    llm = NoLyricsLLM()
    sources = [{"title": "Footage", "duration_seconds": 12}]
    analysis = {
        "frames": [
            {"timestamp": 1, "description": "Opening"},
            {"timestamp": 5, "description": "We rise together"},
            {"timestamp": 8, "description": "Payoff"},
        ]
    }

    build_montage_plan(llm, "Campaign", {}, sources, [analysis], 1, 6)

    assert "CREATOR-SUPPLIED CAMPAIGN LYRICS" not in llm.user


def test_montage_planner_uses_timed_lyric_cues_without_claiming_exact_sync():
    from clipyyy.campaign import build_montage_plan

    class TimedLyricLLM:
        user = ""

        def complete_json(self, system, user, schema, name):
            self.user = user
            return {
                "edits": [
                    {
                        "title": "Timed lyric story",
                        "shots": [
                            {"source_index": 0, "start_seconds": 1, "end_seconds": 3, "reason": "Opening"},
                            {"source_index": 0, "start_seconds": 4, "end_seconds": 6, "reason": "Build"},
                            {"source_index": 0, "start_seconds": 7, "end_seconds": 9, "reason": "Payoff"},
                        ],
                    }
                ]
            }

    llm = TimedLyricLLM()
    source = {"title": "Campaign footage", "duration_seconds": 12}
    analysis = {
        "frames": [
            {"timestamp": 1, "description": "Opening"},
            {"timestamp": 5, "description": "We rise together"},
            {"timestamp": 8, "description": "Payoff"},
        ]
    }
    cues = [
        {"text": "We rise", "start_seconds": 0.0, "end_seconds": 1.2},
        {"text": "Together", "start_seconds": 3.0, "end_seconds": 4.0},
    ]

    edits = build_montage_plan(
        llm,
        "Show a hopeful campaign story.",
        {},
        [source],
        [analysis],
        1,
        6,
        lyric_cues=cues,
    )

    assert len(edits) == 1
    assert "TIMED LYRIC CUES" in llm.user
    assert '"start_seconds": 3.0' in llm.user
    assert "seconds relative to the selected music segment" in llm.user
    assert "do not claim" in llm.user
    assert "LYRIC-TO-SCENE EVIDENCE HINTS" in llm.user
    assert '"matched_terms": ["together"]' in llm.user


def test_lyric_scene_matcher_ranks_only_grounded_visual_keyword_evidence():
    from clipyyy.campaign import _rank_lyric_scene_matches

    cues = [
        {
            "text": "Together we rise",
            "start_seconds": 2.0,
            "end_seconds": 3.0,
        }
    ]
    candidates = [
        {
            "source_index": 0,
            "source_title": "Celebration footage",
            "timestamp": 7.5,
            "description": "A group of friends celebrating together",
            "visible_action": "people raising their hands",
            "subjects": "group of friends",
            "confidence": 0.95,
        },
        {
            "source_index": 1,
            "source_title": "Unrelated footage",
            "timestamp": 4.0,
            "description": "A close-up of a red car on a road",
            "visible_action": "car driving",
            "confidence": 0.99,
        },
        {
            "source_index": 2,
            "source_title": "Text-only footage",
            "timestamp": 5.0,
            "description": "Visual content unavailable for this text-only model",
            "visible_action": "unknown",
            "confidence": 0.0,
        },
    ]

    result = _rank_lyric_scene_matches(cues, candidates)

    assert len(result) == 1
    assert result[0]["cue_text"] == "Together we rise"
    assert result[0]["cue_start_seconds"] == 2.0
    assert len(result[0]["matches"]) == 1
    assert result[0]["matches"][0]["source_index"] == 0
    assert "together" in result[0]["matches"][0]["matched_terms"]
    assert result[0]["matches"][0]["score"] > 0.0


def test_lyric_scene_matcher_does_not_force_unmatched_or_text_only_scenes():
    from clipyyy.campaign import _rank_lyric_scene_matches

    result = _rank_lyric_scene_matches(
        [{"text": "A brighter tomorrow", "start_seconds": 0, "end_seconds": 1}],
        [
            {
                "source_index": 0,
                "timestamp": 2,
                "description": "Visual content unavailable for this text-only model",
            },
            {
                "source_index": 1,
                "timestamp": 3,
                "description": "A person walking beside a lake",
                "visible_action": "walking",
            },
        ],
    )

    expected = {
        "cue_text": "A brighter tomorrow",
        "cue_start_seconds": 0.0,
        "cue_end_seconds": 1.0,
        "matches": [],
    }
    assert result == [expected]


def test_scene_music_matching_pairs_visual_energy_with_selected_music_windows():
    from clipyyy.campaign import _annotate_scene_music_matches

    candidates = [
        {"description": "A person sprinting through a city", "confidence": 0.95},
        {"description": "A calm sunset over a peaceful landscape", "confidence": 0.9},
        {"description": "A person working at a desk", "confidence": 0.8},
        {"description": "An unclassified visual scene", "confidence": 0.9},
        {"description": "A person dancing", "confidence": 0.1},
    ]
    music = {
        "best_start_seconds": 10.0,
        "energy_sections": [
            {"start_seconds": 0, "end_seconds": 9, "level": "high", "average_energy": 0.95},
            {"start_seconds": 10, "end_seconds": 13, "level": "low", "average_energy": 0.12},
            {"start_seconds": 13, "end_seconds": 16, "level": "medium", "average_energy": 0.51},
            {"start_seconds": 16, "end_seconds": 20, "level": "high", "average_energy": 0.91},
            {"start_seconds": 20, "end_seconds": 30, "level": "high", "average_energy": 0.99},
        ],
    }

    _annotate_scene_music_matches(candidates, music, target_seconds=10)

    sprint, sunset, working, unknown, low_confidence = [item["music_alignment"] for item in candidates]
    assert sprint["visual_energy"] == "high"
    assert sprint["evidence"] == ["sprinting"]
    assert sprint["matching_music_windows"][0]["start_seconds"] == 16
    assert sunset["visual_energy"] == "low"
    assert sunset["matching_music_windows"][0]["start_seconds"] == 10
    assert working["visual_energy"] == "medium"
    assert working["matching_music_windows"][0]["level"] == "medium"
    assert unknown["visual_energy"] == "unknown"
    assert unknown["matching_music_windows"] == []
    assert low_confidence["visual_energy"] == "unknown"


def test_scene_music_matching_does_not_invent_music_alignment_without_track():
    from clipyyy.campaign import _annotate_scene_music_matches

    candidates = [{"description": "A person sprinting"}]
    _annotate_scene_music_matches(candidates, None, target_seconds=12)
    assert "music_alignment" not in candidates[0]


def test_creative_director_generates_distinct_edit_directions():
    from clipyyy.campaign import build_montage_concepts

    class DirectionAwareLLM:
        def complete_json(self, system, user, schema, name):
            if "most arresting" in user:
                offset, title = 1, "Hook-first cut"
            elif "satisfying narrative arc" in user:
                offset, title = 5, "Story-build cut"
            else:
                offset, title = 9, "Music-driven cut"
            shots = [
                {
                    "source_index": 0,
                    "start_seconds": offset,
                    "end_seconds": offset + 2,
                    "reason": "opening",
                },
                {
                    "source_index": 0,
                    "start_seconds": offset + 2,
                    "end_seconds": offset + 4,
                    "reason": "build",
                },
                {
                    "source_index": 0,
                    "start_seconds": offset + 4,
                    "end_seconds": offset + 6,
                    "reason": "payoff",
                },
            ]
            return {"edits": [{"title": title, "shots": shots}]}

    source = {"title": "Footage", "duration_seconds": 30}
    analysis = {
        "frames": [
            {"timestamp": 2, "description": "Person running toward camera", "confidence": 0.9},
            {"timestamp": 8, "description": "Close-up of hands building a model", "confidence": 0.9},
            {"timestamp": 14, "description": "People celebrating together", "confidence": 0.9},
        ]
    }
    concepts = build_montage_concepts(
        DirectionAwareLLM(),
        "A short campaign",
        {},
        [source],
        [analysis],
        1,
        6,
        music_analysis={"energy_sections": []},
    )

    assert [concept["id"] for concept in concepts] == [
        "hook-first",
        "story-build",
        "music-driven",
    ]
    assert len({concept["edits"][0]["shots"][0]["start_seconds"] for concept in concepts}) == 3
    assert all(len(concept["edits"][0]["shots"]) == 3 for concept in concepts)


def test_creative_director_text_only_falls_back_to_one_honest_direction():
    from clipyyy.campaign import build_montage_concepts

    class TextOnlyModel:
        def complete_json(self, *args, **kwargs):
            raise AssertionError("Text-only footage must not trigger creative visual inference")

    sources = [{"duration_seconds": 90}]
    analyses = [
        {
            "frames": [
                {
                    "timestamp": 10,
                    "description": "Visual content unavailable: text-only model.",
                }
            ]
        }
    ]
    concepts = build_montage_concepts(
        TextOnlyModel(),
        "Campaign",
        {},
        sources,
        analyses,
        1,
        12,
    )

    assert len(concepts) == 1
    assert concepts[0]["id"] == "balanced"
    assert concepts[0]["edits"]


def test_story_retention_hints_identify_only_observed_story_roles():
    from clipyyy.campaign import _annotate_story_retention_hints

    candidates = [
        {
            "description": "A dramatic close-up of a smiling woman",
            "visible_action": "smiling",
            "confidence": 0.95,
            "shot_scale": "close-up",
        },
        {
            "description": "A person demonstrating a new device by testing it",
            "visible_action": "testing",
            "confidence": 0.9,
        },
        {
            "description": "The finished product and successful results on a table",
            "visible_text": "Learn more and sign up",
            "confidence": 0.88,
        },
        {
            "description": "A landscape with no identifiable action",
            "confidence": 0.2,
        },
    ]

    _annotate_story_retention_hints(candidates)

    hook_roles = [item["role"] for item in candidates[0]["story_retention_hints"]["roles"]]
    assert "hook" in hook_roles
    assert "reaction" in hook_roles
    demo_roles = [item["role"] for item in candidates[1]["story_retention_hints"]["roles"]]
    assert "demonstration" in demo_roles
    payoff_roles = [item["role"] for item in candidates[2]["story_retention_hints"]["roles"]]
    assert "payoff" in payoff_roles
    assert "call_to_action" in payoff_roles
    assert candidates[3]["story_retention_hints"]["unclassified"] is True
    assert candidates[3]["story_retention_hints"]["roles"] == []


def test_story_retention_hints_use_visible_evidence_and_are_added_to_planner_context():
    from clipyyy.campaign import _annotate_story_retention_hints, build_montage_plan

    candidate = {
        "description": "A team celebrating a completed project",
        "confidence": 0.9,
    }
    _annotate_story_retention_hints([candidate])
    assert candidate["story_retention_hints"]["roles"][0]["role"] == "payoff"

    class StoryLLM:
        user = ""
        system = ""

        def complete_json(self, system, user, schema, name):
            self.system = system
            self.user = user
            return {
                "edits": [
                    {
                        "title": "A clear mini story",
                        "shots": [
                            {"source_index": 0, "start_seconds": 1, "end_seconds": 3, "reason": "Opening"},
                            {"source_index": 0, "start_seconds": 4, "end_seconds": 6, "reason": "Build"},
                            {"source_index": 0, "start_seconds": 7, "end_seconds": 9, "reason": "Payoff"},
                        ],
                    }
                ]
            }

    llm = StoryLLM()
    source = {"title": "Campaign footage", "duration_seconds": 12}
    analysis = {
        "frames": [
            {"timestamp": 1, "description": "A dramatic close-up of a smiling person", "confidence": 0.9},
            {"timestamp": 5, "description": "A person demonstrating a device", "confidence": 0.9},
            {"timestamp": 8, "description": "A team celebrating the successful result", "confidence": 0.9},
        ]
    }

    edits = build_montage_plan(llm, "Show the campaign story.", {}, [source], [analysis], 1, 6)

    assert len(edits) == 1
    assert '"role": "hook"' in llm.user
    assert '"role": "demonstration"' in llm.user
    assert '"role": "payoff"' in llm.user
    assert "truthful opening" in llm.system
    assert "Do not force every story role" in llm.system


def test_final_cut_refinement_reorders_only_grounded_story_roles_and_preserves_original():
    from clipyyy.campaign import _refine_final_cut

    edit = {
        "rank": 1,
        "title": "Unordered cut",
        "shots": [
            {"source_index": 0, "start_seconds": 8, "end_seconds": 10, "reason": "payoff"},
            {"source_index": 0, "start_seconds": 1, "end_seconds": 3, "reason": "opening"},
            {"source_index": 0, "start_seconds": 5, "end_seconds": 7, "reason": "build"},
        ],
    }
    sources = [{"duration_seconds": 20}]
    analyses = [
        {
            "frames": [
                {
                    "timestamp": 2,
                    "description": "A dramatic close-up with eye contact",
                    "confidence": 0.95,
                },
                {
                    "timestamp": 6,
                    "description": "A person demonstrating a device by testing it",
                    "confidence": 0.95,
                },
                {
                    "timestamp": 9,
                    "description": "The finished product and successful results",
                    "confidence": 0.95,
                },
            ]
        }
    ]

    refined, notes = _refine_final_cut(edit, sources, analyses)

    assert [shot["start_seconds"] for shot in refined["shots"]] == [1, 5, 8]
    assert notes
    assert [shot["start_seconds"] for shot in edit["shots"]] == [8, 1, 5]


def test_final_cut_refinement_does_not_reorder_when_story_evidence_is_sparse():
    from clipyyy.campaign import _refine_final_cut

    edit = {
        "rank": 1,
        "title": "Original",
        "shots": [
            {"source_index": 0, "start_seconds": 1, "end_seconds": 3, "reason": "one"},
            {"source_index": 0, "start_seconds": 5, "end_seconds": 7, "reason": "two"},
            {"source_index": 0, "start_seconds": 9, "end_seconds": 11, "reason": "three"},
        ],
    }
    analyses = [
        {
            "frames": [
                {"timestamp": 2, "description": "A dramatic close-up", "confidence": 0.9},
                {"timestamp": 6, "description": "An ordinary room", "confidence": 0.9},
                {"timestamp": 10, "description": "A quiet landscape", "confidence": 0.9},
            ]
        }
    ]

    refined, notes = _refine_final_cut(edit, [{"duration_seconds": 20}], analyses)

    assert refined["shots"] == edit["shots"]
    assert notes == []


def test_final_cut_refinement_snaps_small_cut_adjustments_to_detected_beats():
    from clipyyy.campaign import _refine_final_cut

    edit = {
        "rank": 1,
        "title": "Beat cut",
        "shots": [
            {"source_index": 0, "start_seconds": 0, "end_seconds": 2.1, "reason": "one"},
            {"source_index": 0, "start_seconds": 3, "end_seconds": 5, "reason": "two"},
            {"source_index": 0, "start_seconds": 6, "end_seconds": 8, "reason": "three"},
        ],
    }
    refined, notes = _refine_final_cut(
        edit,
        [{"duration_seconds": 20}],
        [{"frames": []}],
        {"best_start_seconds": 0, "beat_times": [2.0, 4.0, 6.0]},
    )

    assert refined["shots"][0]["end_seconds"] == 2.0
    assert any("beat" in note.lower() for note in notes)
    assert edit["shots"][0]["end_seconds"] == 2.1


def test_final_cut_refinement_never_snaps_a_cut_through_black_footage():
    from clipyyy.campaign import _refine_final_cut

    edit = {
        "rank": 1,
        "title": "Black-frame guard",
        "shots": [
            {"source_index": 0, "start_seconds": 0, "end_seconds": 2.1, "reason": "one"},
            {"source_index": 0, "start_seconds": 3, "end_seconds": 5, "reason": "two"},
            {"source_index": 0, "start_seconds": 6, "end_seconds": 8, "reason": "three"},
        ],
    }
    refined, notes = _refine_final_cut(
        edit,
        [{"duration_seconds": 20}],
        [{"frames": [], "black_intervals": [[1.95, 2.05]]}],
        {"best_start_seconds": 0, "beat_times": [2.0]},
    )

    assert refined["shots"][0]["end_seconds"] == 2.1
    assert not any("beat" in note.lower() for note in notes)


def test_visual_continuity_flags_adjacent_near_duplicate_shots():
    from clipyyy.campaign import _visual_continuity_notes

    sources = [{"duration_seconds": 20}]
    analyses = [
        {
            "frames": [
                {
                    "timestamp": 3,
                    "description": "A woman smiling while holding a red coffee cup",
                    "subjects": "woman, coffee cup",
                    "shot_scale": "close-up",
                    "visible_action": "holding coffee cup",
                    "confidence": 0.9,
                },
                {
                    "timestamp": 6,
                    "description": "A woman smiling while holding a red coffee cup",
                    "subjects": "woman, coffee cup",
                    "shot_scale": "close-up",
                    "visible_action": "holding coffee cup",
                    "confidence": 0.9,
                },
            ]
        }
    ]
    edit = {
        "shots": [
            {"source_index": 0, "start_seconds": 2, "end_seconds": 4},
            {"source_index": 0, "start_seconds": 5, "end_seconds": 7},
        ]
    }

    notes = _visual_continuity_notes(edit, sources, analyses)

    assert any("Potentially repetitive adjacent shots: 1–2" in note for note in notes)
    assert any("sampled still frames" in note for note in notes)


def test_visual_continuity_does_not_flag_distinct_framing_as_duplicate():
    from clipyyy.campaign import _visual_continuity_notes

    sources = [{"duration_seconds": 20}]
    analyses = [
        {
            "frames": [
                {
                    "timestamp": 3,
                    "description": "A wide view of a busy kitchen with several people",
                    "subjects": "kitchen, people",
                    "shot_scale": "wide",
                    "visible_action": "people preparing food",
                    "confidence": 0.9,
                },
                {
                    "timestamp": 6,
                    "description": "Close detail of hands chopping vegetables",
                    "subjects": "hands, vegetables",
                    "shot_scale": "detail",
                    "visible_action": "chopping vegetables",
                    "confidence": 0.95,
                },
            ]
        }
    ]
    edit = {
        "shots": [
            {"source_index": 0, "start_seconds": 2, "end_seconds": 4},
            {"source_index": 0, "start_seconds": 5, "end_seconds": 7},
        ]
    }

    notes = _visual_continuity_notes(edit, sources, analyses)

    assert not any("Potentially repetitive" in note for note in notes)
    assert notes == []


def test_visual_continuity_is_honest_when_visual_evidence_is_unavailable():
    from clipyyy.campaign import _visual_continuity_notes

    sources = [{"duration_seconds": 20}]
    analyses = [
        {
            "frames": [
                {
                    "timestamp": 3,
                    "description": "Visual content unavailable: installed model is text-only.",
                    "confidence": 0.0,
                }
            ]
        }
    ]
    edit = {
        "shots": [
            {"source_index": 0, "start_seconds": 2, "end_seconds": 4},
            {"source_index": 0, "start_seconds": 5, "end_seconds": 7},
            {"source_index": 0, "start_seconds": 8, "end_seconds": 10},
        ]
    }

    notes = _visual_continuity_notes(edit, sources, analyses)

    assert notes == []


class FakeAiEditLLM:
    def __init__(self):
        self.user_prompt = ""

    def complete_json(self, system, user, schema, name):
        self.user_prompt = user
        return {
            "shots": [
                {"candidate_index": 0, "start_seconds": 1, "end_seconds": 3, "reason": "Current opening"},
                {"candidate_index": 1, "start_seconds": 8, "end_seconds": 10, "reason": "New angle"},
                {"candidate_index": 2, "start_seconds": 14, "end_seconds": 16, "reason": "Payoff"},
            ],
            "notes": ["A stronger sequence across the campaign footage."],
        }


def test_ai_edit_can_reuse_verified_shots_from_other_campaign_clips():
    llm = FakeAiEditLLM()
    current_edit = {
        "rank": 1,
        "title": "Selected clip",
        "shots": [
            {"source_index": 0, "start_seconds": 1, "end_seconds": 4, "reason": "Current opening"},
        ],
    }
    other_edits = [
        {
            "rank": 2,
            "title": "Alternate clip",
            "shots": [
                {"source_index": 1, "start_seconds": 8, "end_seconds": 11, "reason": "New angle"},
                {"source_index": 0, "start_seconds": 14, "end_seconds": 17, "reason": "Payoff"},
            ],
        }
    ]
    sources = [
        {"title": "Main footage", "duration_seconds": 30},
        {"title": "Second footage", "duration_seconds": 30},
    ]

    proposal, notes = generate_ai_edit_proposal(
        llm,
        "Show the product clearly",
        current_edit,
        sources,
        "More energetic",
        candidate_edits=other_edits,
    )

    assert proposal["rank"] == 1
    assert [shot["source_index"] for shot in proposal["shots"]] == [0, 1, 0]
    assert "Alternate clip" in llm.user_prompt
    assert "origin_clip_rank" in llm.user_prompt
    assert notes == ["A stronger sequence across the campaign footage."]

def test_creator_lyrics_align_to_whisper_word_timestamps_and_reports_unmatched_words():
    from clipyyy.transcribe import align_lyric_text_to_words

    transcript = [
        {"word": "Intro", "start": 0.0, "end": 0.4},
        {"word": "We", "start": 1.0, "end": 1.2},
        {"word": "rise", "start": 1.25, "end": 1.6},
        {"word": "tonight", "start": 1.7, "end": 2.2},
    ]

    result = align_lyric_text_to_words("We rise forever tonight", transcript)

    assert [item["word"] for item in result["words"]] == ["We", "rise", "tonight"]
    assert [item["start"] for item in result["words"]] == [1.0, 1.25, 1.7]
    assert result["unmatched_words"] == ["forever"]
    assert result["word_count"] == 4
    assert result["matched_count"] == 3
    assert result["match_percent"] == 75


def test_creator_lyrics_alignment_rejects_empty_or_oversized_input():
    from clipyyy.transcribe import align_lyric_text_to_words

    with pytest.raises(ValueError, match="Enter lyrics"):
        align_lyric_text_to_words("   ", [{"word": "hello", "start": 0, "end": 1}])
    with pytest.raises(ValueError, match="up to 1"):
        align_lyric_text_to_words("one two", [{"word": "one", "start": 0, "end": 1}], max_lyrics_words=1)

