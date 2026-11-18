import json

import httpx
import pytest

from clipyyy import db
from clipyyy.llm import PROVIDERS, LLMError, OpenAICompatibleLLM, get_llm, parse_json


def make_llm(handler):
    return OpenAICompatibleLLM(
        PROVIDERS["openrouter"], "key", "some/model", transport=httpx.MockTransport(handler)
    )


def reply(content, status=200):
    return httpx.Response(status, json={"choices": [{"message": {"content": content}}]})


def test_sends_structured_output_request():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers["authorization"]
        seen["url"] = str(request.url)
        return reply('{"clips": []}')

    assert make_llm(handler).complete_json("sys", "user", {"type": "object"}, "x") == {"clips": []}
    assert seen["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert seen["auth"] == "Bearer key"
    assert seen["body"]["model"] == "some/model"
    assert seen["body"]["response_format"]["json_schema"]["strict"] is True


def test_falls_back_when_model_rejects_response_format():
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append("response_format" in body)
        if "response_format" in body:
            return httpx.Response(400, text="response_format not supported")
        return reply('```json\n{"ok": true}\n```')

    assert make_llm(handler).complete_json("s", "u", {}, "x") == {"ok": True}
    assert calls == [True, False]


def test_errors_are_raised():
    with pytest.raises(LLMError, match="401"):
        make_llm(lambda r: httpx.Response(401, text="bad key")).complete_json("s", "u", {}, "x")


def test_parse_json_handles_prose():
    assert parse_json('Here you go: {"a": 1} thanks') == {"a": 1}
    with pytest.raises(LLMError):
        parse_json("no json here")


def test_get_llm_requires_key_and_uses_settings():
    with pytest.raises(LLMError, match="No API key"):
        get_llm()
    db.set_setting("openrouter_api_key", "sk-test")
    db.set_setting("llm_model", "x/y")
    assert get_llm().model == "x/y"
    assert get_llm("override/model").model == "override/model"


def test_ollama_provider_needs_no_api_key_and_sends_no_auth_header():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return reply('{"clips": []}')

    llm = OpenAICompatibleLLM(PROVIDERS["ollama"], "", "qwen2.5:1.5b", transport=httpx.MockTransport(handler))
    assert llm.complete_json("sys", "user", {"type": "object"}, "x") == {"clips": []}
    assert seen["url"] == "http://127.0.0.1:11434/v1/chat/completions"
    assert seen["auth"] is None
    assert seen["body"]["model"] == "qwen2.5:1.5b"


def test_ollama_timeout_is_not_retryable():
    def handler(request):
        raise httpx.ReadTimeout("local model did not respond")

    llm = OpenAICompatibleLLM(PROVIDERS["ollama"], "", "qwen2.5:1.5b", transport=httpx.MockTransport(handler))
    with pytest.raises(LLMError) as error:
        llm.complete_json("sys", "user", {"type": "object"}, "x")
    assert error.value.retryable is False


def test_get_llm_uses_local_default_model(monkeypatch):
    from clipyyy import llm as llm_module

    values = {"llm_provider": "ollama", "llm_model": "google/gemini-3.8-flash"}
    monkeypatch.setattr(llm_module, "get_setting", lambda key: values.get(key, ""))
    client = get_llm()
    assert client.provider.name == "Ollama (local)"
    assert client.model == "qwen2.5:1.5b"


def test_gemini_provider_uses_openai_compatible_endpoint_and_bearer_key():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        return reply('{"clips": []}')

    llm = OpenAICompatibleLLM(
        PROVIDERS["gemini"],
        "gemini-test-key",
        "gemini-2.5-flash",
        transport=httpx.MockTransport(handler),
    )
    assert llm.complete_json("sys", "user", {"type": "object"}, "x") == {"clips": []}
    assert seen["url"] == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    assert seen["auth"] == "Bearer gemini-test-key"


def test_get_llm_uses_gemini_key_setting(monkeypatch):
    from clipyyy import llm as llm_module

    values = {
        "llm_provider": "gemini",
        "llm_model": "gemini-2.5-flash",
        "gemini_api_key": "gemini-test-key",
    }
    monkeypatch.setattr(llm_module, "get_setting", lambda key: values.get(key, ""))
    client = get_llm()
    assert client.provider.name == "Google Gemini"
    assert client.model == "gemini-2.5-flash"



def test_gemini_retries_with_current_model_when_old_model_is_retired():
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body["model"])
        if body["model"] == "gemini-2.5-flash":
            return httpx.Response(
                404,
                json={"error": {"message": "This model models/gemini-2.5-flash is no longer available to new users."}},
            )
        return reply('{"clips": []}')

    llm = OpenAICompatibleLLM(
        PROVIDERS["gemini"],
        "gemini-test-key",
        "gemini-2.5-flash",
        transport=httpx.MockTransport(handler),
    )
    assert llm.complete_json("s", "u", {"type": "object"}, "x") == {"clips": []}
    assert calls == ["gemini-2.5-flash", "gemini-3.8-flash"]
    assert llm.model == "gemini-3.8-flash"


def test_gemini_image_request_retries_with_current_model_when_old_model_is_retired(tmp_path):
    image_path = tmp_path / "frame.jpg"
    image_path.write_bytes(b"fake-jpeg")
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body["model"])
        if body["model"] == "gemini-2.5-flash":
            return httpx.Response(
                404,
                json={"error": {"message": "This model is no longer available to new users."}},
            )
        return reply('{"ok": true}')

    llm = OpenAICompatibleLLM(
        PROVIDERS["gemini"],
        "gemini-test-key",
        "gemini-2.5-flash",
        transport=httpx.MockTransport(handler),
    )
    assert llm.complete_json_with_images("s", "u", {"type": "object"}, "x", [(1.0, image_path)]) == {"ok": True}
    assert calls == ["gemini-2.5-flash", "gemini-3.8-flash"]
