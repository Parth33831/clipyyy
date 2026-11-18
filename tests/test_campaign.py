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
