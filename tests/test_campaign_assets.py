from pathlib import Path

from clipyyy import campaign_assets


def test_campaign_search_queries_derive_concise_phrases():
    queries = campaign_assets.campaign_search_queries(
        {
            "subject_or_theme": "Urban running",
            "content_type": "sports campaign",
            "mood": ["energetic", "hopeful"],
            "visual_style_and_pacing": ["fast cuts", "dynamic movement"],
        }
    )
    assert queries[0] == "Urban running"
    assert "Urban running energetic hopeful" in queries
    assert len(queries) <= 3


def test_campaign_search_queries_have_a_brief_fallback():
    queries = campaign_assets.campaign_search_queries({}, "A bright futuristic technology launch")
    assert queries
    assert "bright futuristic technology launch" in queries[0]


def test_discovery_skips_cleanly_without_a_pexels_key(tmp_path):
    assets, status = campaign_assets.discover_campaign_assets(
        {"subject_or_theme": "running"}, tmp_path, ""
    )
    assert assets == []
    assert status["status"] == "skipped_missing_pexels_key"
    assert not (tmp_path / "campaign-stock").exists()


def test_discovery_deduplicates_results_and_records_attribution(tmp_path, monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "videos": [
                    {
                        "id": 42,
                        "duration": 12,
                        "url": "https://www.pexels.com/video/42/",
                        "user": {"name": "Creator"},
                        "video_files": [
                            {
                                "link": "https://videos.pexels.com/video.mp4",
                                "width": 720,
                                "height": 1280,
                            }
                        ],
                    }
                ]
            }

    class FakeClient:
        def __init__(self, **kwargs):
            self.queries = []

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, params):
            self.queries.append(params["query"])
            return FakeResponse()

    monkeypatch.setattr(campaign_assets.httpx, "Client", FakeClient)

    def fake_download(url, path):
        path.write_bytes(b"video")

    monkeypatch.setattr(campaign_assets, "_download_video", fake_download)
    monkeypatch.setattr(campaign_assets, "probe", lambda path: (720, 1280, 12.0))

    assets, status = campaign_assets.discover_campaign_assets(
        {
            "subject_or_theme": "Urban running",
            "mood": ["energetic"],
        },
        tmp_path,
        "free-pexels-test-key",
        max_assets=3,
    )

    assert len(assets) == 1
    assert status["status"] == "added"
    assert assets[0]["source_kind"] == "pexels"
    assert assets[0]["credit"] == "Video by Creator on Pexels"
    assert assets[0]["credit_url"] == "https://www.pexels.com/video/42/"
    assert Path(assets[0]["video_path"]).is_file()


def test_best_video_file_prefers_requested_orientation():
    files = [
        {"link": "landscape.mp4", "width": 1920, "height": 1080},
        {"link": "portrait.mp4", "width": 720, "height": 1280},
    ]
    selected = campaign_assets._best_video_file(files, "portrait")
    assert selected["link"] == "portrait.mp4"


def test_text_only_campaign_keeps_creator_footage_primary_with_stock_inserts():
    from clipyyy.campaign import _build_text_only_montage

    sources = [
        {"duration_seconds": 120.0, "source_kind": "creator"},
        {"duration_seconds": 120.0, "source_kind": "pexels", "search_query": "urban running"},
    ]
    unavailable = {
        "frames": [
            {
                "timestamp": float(timestamp),
                "description": "Visual content unavailable: installed model is text-only.",
            }
            for timestamp in range(5, 115, 5)
        ]
    }
    edits = _build_text_only_montage(sources, output_count=1, target_seconds=20, analyses=[unavailable, unavailable])
    shots = edits[0]["shots"]
    stock_shots = [shot for shot in shots if shot["source_index"] == 1]
    creator_shots = [shot for shot in shots if shot["source_index"] == 0]

    assert stock_shots
    assert len(creator_shots) > len(stock_shots)
    assert all("text-only model did not inspect" in shot["reason"] for shot in stock_shots)


def test_campaign_auto_broll_option_is_off_by_default():
    from clipyyy.pipeline import ClipOptions

    assert ClipOptions(campaign_mode=True).campaign_auto_broll is False
