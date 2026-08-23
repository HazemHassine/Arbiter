import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from dev_agent.api.app import create_app
from dev_agent.llm.openai_compatible import LLMProviderError, OpenAICompatibleProvider


def test_chat_provider_disables_reasoning_for_function_tools():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "OK"}}]})

    provider = OpenAICompatibleProvider(
        "https://example.test/v1", "test-key", "gpt-test", transport=httpx.MockTransport(handler)
    )
    response = asyncio.run(provider.complete([{"role": "user", "content": "hello"}], []))
    assert captured["reasoning_effort"] == "none"
    assert response["content"] == "OK"


def test_chat_provider_surfaces_sanitized_api_error():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"error": {"type": "invalid_request_error", "message": "reasoning effort is invalid"}},
        )

    provider = OpenAICompatibleProvider(
        "https://example.test/v1", "test-key", "gpt-test", transport=httpx.MockTransport(handler)
    )
    with pytest.raises(LLMProviderError, match="reasoning effort is invalid") as raised:
        asyncio.run(provider.complete([{"role": "user", "content": "hello"}], []))
    assert raised.value.status_code == 400
    assert raised.value.code == "invalid_request_error"


def test_agent_api_degrades_instead_of_returning_500(service_factory, monkeypatch):
    services = service_factory()
    services.settings.llm_api_key = "test-key"
    services.settings.llm_model = "gpt-test"

    async def fail(*_args, **_kwargs):
        raise LLMProviderError("upstream rejected this request", status_code=400)

    monkeypatch.setattr(OpenAICompatibleProvider, "complete", fail)
    with TestClient(create_app(services=services)) as client:
        response = client.post("/api/v1/agent/query", json={"message": "Explain my environment"})
    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert "upstream rejected" in response.json()["message"]
