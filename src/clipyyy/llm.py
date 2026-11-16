"""Model-agnostic LLM access via OpenAI-compatible chat completions.

Supports hosted OpenRouter and a zero-cost local Ollama server.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from clipyyy.config import get_setting


class LLMError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


class LLM(Protocol):
    model: str

    def complete_json(self, system: str, user: str, schema: dict[str, Any], name: str) -> dict: ...


@dataclass(frozen=True, slots=True)
class Provider:
    name: str
    base_url: str
    key_setting: str
    headers: dict[str, str] = field(default_factory=dict)
    local: bool = False


PROVIDERS: dict[str, Provider] = {
    "openrouter": Provider(
        name="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        key_setting="openrouter_api_key",
        headers={"HTTP-Referer": "https://github.com/T3-Venture-Labs-Limited/clipyyy", "X-Title": "clipyyy"},
    ),
    "ollama": Provider(
        name="Ollama (local)",
        base_url="http://127.0.0.1:11434/v1",
        key_setting="",
        local=True,
    ),
}


class OpenAICompatibleLLM:
    def __init__(
        self,
        provider: Provider,
        api_key: str,
        model: str,
        transport: httpx.BaseTransport | None = None,
        timeout: float | None = None,
    ) -> None:
        if provider.key_setting and not api_key:
            raise LLMError(
                f"No API key for {provider.name}. Add it in Settings or run "
                f"`clipyyy config set {provider.key_setting} <key>`."
            )
        self.provider = provider
        self.model = model
        # Local inference can be slower, but must not leave a pipeline hanging indefinitely.
        request_timeout = timeout if timeout is not None else (120.0 if provider.local else 300.0)
        self._client = httpx.Client(
            base_url=provider.base_url,
            headers={"Authorization": f"Bearer {api_key}", **provider.headers} if api_key else provider.headers,
            timeout=httpx.Timeout(request_timeout, connect=5.0),
            transport=transport,
        )

    def complete_json(self, system: str, user: str, schema: dict[str, Any], name: str) -> dict:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": name, "strict": True, "schema": schema},
            },
        }
        response = self._post(body)
        if response.status_code == 400 and "response_format" in response.text:
            # Some local models reject schema mode; the prompt still explicitly requests JSON.
            body.pop("response_format")
            response = self._post(body)
        if response.status_code >= 400:
            raise LLMError(f"{self.provider.name} error {response.status_code}: {response.text[:500]}")

        payload = response.json()
        if "error" in payload:
            raise LLMError(f"{self.provider.name} error: {payload['error']}")
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"Unexpected response from {self.provider.name}: {payload}") from exc
        return parse_json(content)

    def _post(self, body: dict[str, Any]) -> httpx.Response:
        # A local model request is expensive; retrying a stalled inference multiplies wait time.
        attempts = 1 if self.provider.local else 4
        delay = 2.0
        for attempt in range(attempts):
            try:
                response = self._client.post("/chat/completions", json=body)
            except httpx.TimeoutException as exc:
                raise LLMError(
                    f"{self.provider.name} request timed out after the configured limit.",
                    retryable=False,
                ) from exc
            except httpx.TransportError as exc:
                if self.provider.local or attempt == attempts - 1:
                    raise LLMError(
                        f"{self.provider.name} connection failed: {exc}",
                        retryable=not self.provider.local,
                    ) from exc
            else:
                if response.status_code not in {429, 500, 502, 503, 504} or attempt == attempts - 1:
                    return response
            time.sleep(delay)
            delay *= 2
        raise AssertionError("unreachable")


def parse_json(content: Any) -> dict:
    if isinstance(content, list):
        content = "".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
    text = str(content or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise LLMError(f"Model did not return JSON: {text[:200]}")
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise LLMError(f"Model returned invalid JSON: {exc}: {text[:200]}") from exc


def get_llm(model: str | None = None) -> LLM:
    provider_key = get_setting("llm_provider") or "openrouter"
    provider = PROVIDERS.get(provider_key)
    if provider is None:
        raise LLMError(f"Unknown LLM provider '{provider_key}'. Available: {', '.join(PROVIDERS)}")
    selected_model = model or get_setting("llm_model")
    if provider.local and not selected_model:
        selected_model = "qwen2.5:1.5b"
    return OpenAICompatibleLLM(
        provider,
        get_setting(provider.key_setting) if provider.key_setting else "",
        selected_model,
    )


def list_models() -> list[dict[str, Any]]:
    """List models exposed by the selected provider (including local Ollama models)."""
    provider = PROVIDERS[get_setting("llm_provider") or "openrouter"]
    response = httpx.get(f"{provider.base_url}/models", timeout=10 if provider.local else 30)
    response.raise_for_status()
    models = []
    for item in response.json().get("data", []):
        params = item.get("supported_parameters") or []
        if item["id"].endswith(":batch"):
            continue
        if params and "structured_outputs" not in params and "response_format" not in params:
            continue
        pricing = item.get("pricing") or {}
        models.append(
            {
                "id": item["id"],
                "name": item.get("name", item["id"]),
                "context_length": item.get("context_length"),
                "prompt_price_per_million": _per_million(pricing.get("prompt")),
                "completion_price_per_million": _per_million(pricing.get("completion")),
            }
        )
    return sorted(models, key=lambda m: m["id"])


def _per_million(value: Any) -> float | None:
    try:
        return round(float(value) * 1_000_000, 4)
    except (TypeError, ValueError):
        return None
