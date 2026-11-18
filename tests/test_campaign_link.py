from clipyyy import campaign_link


class FakeResponse:
    status_code = 200
    headers = {"content-type": "text/html; charset=utf-8"}
    encoding = "utf-8"
    content = b"""
    <html><head><title>Summer Creator Challenge</title>
    <meta name="description" content="Create a summer product video">
    <meta property="og:video" content="https://cdn.example.com/reference.mp4">
    </head><body>
    <h1>Campaign rules</h1><p>Publish one vertical video between 20 and 30 seconds.
    Show the product clearly. Do not use competitor logos. Use the official campaign sound.</p>
    <a href="https://example.com/reference">Example video</a>
    <a href="https://example.com/terms">Terms</a>
    </body></html>
    """


class FakeClient:
    def __init__(self, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get(self, url, headers):
        return FakeResponse()


def test_import_campaign_page_extracts_rules_and_reference_links(monkeypatch):
    monkeypatch.setattr(campaign_link, "_validate_public_url", lambda url: None)
    monkeypatch.setattr(campaign_link.httpx, "Client", FakeClient)

    result = campaign_link.import_campaign_page("https://campaign.example/details")

    assert result["title"] == "Summer Creator Challenge"
    assert "Do not use competitor logos" in result["text"]
    assert result["links"][0] == {
        "url": "https://example.com/reference",
        "text": "Example video",
    }
    assert result["video_urls"] == ["https://cdn.example.com/reference.mp4"]


def test_import_campaign_page_rejects_non_web_urls():
    import pytest

    with pytest.raises(ValueError, match="public http"):
        campaign_link.import_campaign_page("file:///etc/passwd")


def test_import_campaign_page_rejects_localhost():
    import pytest

    with pytest.raises(ValueError, match="private-network"):
        campaign_link._validate_public_url("http://localhost:8000/campaign")
