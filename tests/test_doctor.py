from types import SimpleNamespace

from clipyyy import doctor


def test_ollama_is_a_valid_llm_provider_without_api_key(monkeypatch):
    settings = {
        "llm_provider": "ollama",
        "llm_model": "qwen2.5:1.5b",
        "openrouter_api_key": "",
        "pexels_api_key": "",
        "buffer_api_key": "",
    }
    monkeypatch.setattr(doctor, "get_setting", lambda key: settings.get(key, ""))
    monkeypatch.setattr(
        doctor,
        "find_ffmpeg",
        lambda: SimpleNamespace(ffmpeg="ffmpeg", ffprobe="ffprobe", libass=True),
    )
    monkeypatch.setattr(doctor, "js_runtime", lambda: "node: test")
    monkeypatch.setattr(doctor, "storage_configured", lambda: False)
    monkeypatch.setattr(
        doctor.httpx,
        "get",
        lambda *args, **kwargs: SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"data": [{"id": "qwen2.5:1.5b"}]},
        ),
    )

    llm_check = next(check for check in doctor.checks() if check["name"] == "llm")

    assert llm_check["ok"] is True
    assert llm_check["required"] is True
    assert "Ollama (local)" in llm_check["detail"]
    assert "qwen2.5:1.5b" in llm_check["detail"]
